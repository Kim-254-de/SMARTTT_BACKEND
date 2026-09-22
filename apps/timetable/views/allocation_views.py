from __future__ import annotations

import os
import shutil
import tempfile
import uuid

from django.db import transaction
from django.db.models import Count
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.services.cache_service import PersonalizationCacheService
from apps.timetable.models import AllocationDocument
from apps.timetable.permissions import CanManageTimetable
from apps.timetable.services.allocation_parser import (
    convert_doc_to_docx,
    detect_department,
    parse_allocation_docx,
    parse_allocation_pdf,
)
from apps.timetable.services.allocation_service import (
    LecturerDirectory,
    apply_plan,
    plan_for_year,
    resolve_academic_year,
    tag_rows,
    year_slots,
)

VALID_ALLOCATION_EXTENSIONS = {".docx", ".doc", ".pdf"}


def _parse_upload(file_obj) -> tuple[list[dict], str]:
    """Returns (rows, department named in the document's letterhead or '')."""
    _, ext = os.path.splitext(file_obj.name.lower())
    if ext == ".pdf":
        return parse_allocation_pdf(file_obj), ""

    tmp_dir = tempfile.mkdtemp(prefix="alloc_")
    try:
        path = os.path.join(tmp_dir, os.path.basename(file_obj.name))
        with open(path, "wb") as f:
            for chunk in file_obj.chunks():
                f.write(chunk)
        if ext == ".doc":
            path = convert_doc_to_docx(path)
        try:
            return parse_allocation_docx(path), detect_department(path)
        finally:
            if ext == ".doc":
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _row_summary(row: dict) -> dict:
    return {
        "unit_code": row.get("raw_unit_code") or row.get("unit_code"),
        "lecturer": row.get("lecturer_name"),
        "programme": row.get("programme") or row.get("section"),
        "year_semester": (
            f"Y{row['year_of_study']}S{row['semester']}" if row.get("year_of_study") else None
        ),
        "group": row.get("group") or None,
        "department": row.get("department"),
        "file": row.get("source_file"),
    }


def _conflict_report(conflicts: list[dict], slot_refs: dict) -> list[dict]:
    report = []
    for c in conflicts:
        ref = slot_refs[c["slot_id"]]
        report.append({
            "slot_id": str(c["slot_id"]),
            "unit_code": ref.unit_code,
            "program": ref.program_code,
            "year_of_study": ref.year_of_study,
            "stream": ref.stream or None,
            "class_group": ref.class_group,
            "candidates": [_row_summary(r) for r in c["rows"]],
        })
    return report


def _clear_cache() -> None:
    # Invalidate student cache across Redis/memory
    try:
        PersonalizationCacheService.clear_all()
    except Exception:
        pass


class AssignLecturersAPIView(APIView):
    """
    Department course-allocation documents for the master timetable.

    POST  upload one department's document (.docx, .doc or .pdf) as `file`.
          Departments upload separately and in any order: the document is stored
          under its department (read from the "DEPARTMENT OF ..." letterhead, or
          the `source` field), replacing that department's previous upload, and
          lecturers are re-resolved across every department's stored document.
          Rows are pinned to the exact slots of their unit, programme,
          year/semester and group (see allocation_matcher). When two departments
          name different lecturers for the same class, the slot keeps its current
          lecturer and the clash is returned under `conflicts`.
          Optional: `academic_year` (defaults to the current term's), `dry_run=true`.
    GET   list the year's uploaded documents.
    DELETE `?source=<department>` removes that department's document and the
          lecturers it assigned.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [CanManageTimetable]

    def _academic_year(self, request):
        return resolve_academic_year(request.data.get("academic_year") or request.query_params.get("academic_year"))

    def get(self, request, *args, **kwargs):
        academic_year = self._academic_year(request)
        documents = (
            AllocationDocument.objects.filter(academic_year=academic_year)
            .select_related("uploaded_by")
            .annotate(slots_assigned=Count("assigned_slots"))
        )
        return Response({
            "academic_year": academic_year,
            "documents": [
                {
                    "source": d.source,
                    "file_name": d.file_name,
                    "rows": len(d.rows),
                    "slots_assigned": d.slots_assigned,
                    "uploaded_by": d.uploaded_by.get_full_name() if d.uploaded_by else None,
                    "uploaded_at": d.updated_at,
                }
                for d in documents
            ],
        })

    def delete(self, request, *args, **kwargs):
        academic_year = self._academic_year(request)
        source = (request.query_params.get("source") or request.data.get("source") or "").strip()
        document = AllocationDocument.objects.filter(academic_year=academic_year, source__iexact=source).first()
        if not document:
            return Response({"detail": f"No allocation from '{source}' for {academic_year}."},
                            status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            # Clear what this department set before re-resolving, so slots it alone
            # covered (or was holding in a conflict) don't keep its lecturer.
            document.assigned_slots.update(lecturer=None, lecturer_name_text="", allocation_document=None)
            document.delete()
        remaining = list(AllocationDocument.objects.filter(academic_year=academic_year))
        plan, _refs = plan_for_year(academic_year, remaining)
        applied = apply_plan(academic_year, plan, LecturerDirectory())
        _clear_cache()
        return Response({
            "detail": f"Removed the allocation from {document.source}.",
            "slots_assigned": len(plan["assignments"]),
            "slots_updated": applied["updated"],
        })

    def post(self, request, *args, **kwargs):
        uploads = request.FILES.getlist("file") + request.FILES.getlist("files")
        if len(uploads) != 1:
            return Response(
                {"detail": "Upload one department's allocation document at a time as `file`."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        file_obj = uploads[0]
        _, ext = os.path.splitext(file_obj.name.lower())
        if ext not in VALID_ALLOCATION_EXTENSIONS:
            return Response(
                {"detail": f"Only .docx, .doc or .pdf files are supported. Got: {file_obj.name}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        academic_year = self._academic_year(request)
        if not academic_year:
            return Response(
                {"detail": "No academic term exists yet; upload the master timetable first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not year_slots(academic_year).exists():
            return Response(
                {"detail": f"The master timetable for {academic_year} has no slots to allocate lecturers to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            rows, department = _parse_upload(file_obj)
        except Exception as e:
            return Response(
                {"detail": f"Could not parse {file_obj.name}: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not rows:
            return Response(
                {"detail": "No valid allocation rows found in the document."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        source = (request.data.get("source") or department or os.path.splitext(file_obj.name)[0]).strip()[:150]
        dry_run = str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes"}
        existing = AllocationDocument.objects.filter(academic_year=academic_year, source__iexact=source).first()
        replaced = bool(existing)

        if dry_run:
            document_id = str(existing.id) if existing else str(uuid.uuid4())
        else:
            with transaction.atomic():
                document = existing or AllocationDocument(academic_year=academic_year, source=source)
                document.file_name = file_obj.name
                document.rows = rows
                document.uploaded_by = request.user if request.user.is_authenticated else None
                document.save()
            document_id = str(document.id)
            source = document.source

        rows = tag_rows(rows, document_id, source, file_obj.name)
        others = list(AllocationDocument.objects.filter(academic_year=academic_year).exclude(id=document_id))
        plan, slot_refs = plan_for_year(academic_year, others, extra_rows=rows)

        directory = LecturerDirectory()
        applied = {"updated": 0, "cleared": 0, "overridden": []}
        if not dry_run:
            applied = apply_plan(academic_year, plan, directory)
            _clear_cache()

        def ours(row: dict) -> bool:
            return row.get("document_id") == document_id

        results = []
        for m in plan["matches"]:
            if not ours(m.row):
                continue
            won = [sid for sid in m.slot_ids if sid in plan["assignments"] and plan["assignments"][sid][0] is m.row]
            results.append({
                **_row_summary(m.row),
                "matched_by": m.scope,
                "slots_matched": len(m.slot_ids),
                "slots_assigned": len(won),
                "account_linked": directory.match(m.row["lecturer_name"]) is not None,
            })
        not_found = [{**_row_summary(r), "reason": why} for r, why in plan["skipped"] if ours(r)]
        # Only clashes this document takes part in; the rest were reported when their documents were uploaded.
        conflicts = _conflict_report([c for c in plan["conflicts"] if any(ours(r) for r in c["rows"])], slot_refs)

        return Response({
            "detail": (
                f"{'Previewed' if dry_run else 'Saved'} {len(rows)} allocation row(s) from {source}"
                f"{' (replacing its previous upload)' if replaced else ''}."
            ),
            "academic_year": academic_year,
            "source": source,
            "dry_run": dry_run,
            "departments_on_file": sorted({d.source for d in others} | {source}),
            "matched": len(results),
            "unmatched": len(not_found),
            "slots_assigned_by_this_document": sum(
                1 for row, _ in plan["assignments"].values() if ours(row)
            ),
            "slots_assigned_all_departments": len(plan["assignments"]),
            "slots_updated": applied["updated"],
            "slots_cleared": applied["cleared"],
            "reassigned_from_other_departments": [
                {"slot_id": str(sid), "previous_lecturer": prev, **_row_summary(row)}
                for sid, prev, row in applied["overridden"]
            ],
            "conflict_slots": len(conflicts),
            "results": results,
            "not_found": not_found,
            "conflicts": conflicts,
        })

from __future__ import annotations

import os
import re
from django.db.models import Q
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.lecturers.models import Lecturer
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.permissions import CanManageTimetable
from apps.timetable.services.allocation_parser import (
    parse_allocation_docx,
    parse_allocation_pdf,
)

VALID_ALLOCATION_EXTENSIONS = {".docx", ".pdf"}


def _clean_name(name: str) -> str:
    """Removes titles, tags like (FT)/(PT), and collapses whitespace."""
    cleaned = re.sub(r"\(.*?\)", "", name)
    cleaned = re.sub(r"\b(dr|prof|mr|mrs|ms)\b\.?", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip().lower()


def _match_lecturer(lecturer_name: str) -> Lecturer | None:
    """Matches name against Lecturer first/last names or combined full name."""
    target = _clean_name(lecturer_name)
    if not target:
        return None

    for lecturer in Lecturer.objects.select_related("user").all():
        full_name = _clean_name(lecturer.user.get_full_name())
        if not full_name:
            continue
        if target == full_name or target in full_name or full_name in target:
            return lecturer

        target_tokens = set(target.split())
        lecturer_tokens = set(full_name.split())
        if target_tokens and target_tokens.issubset(lecturer_tokens):
            return lecturer

    return None


class AssignLecturersAPIView(APIView):
    """
    Upload a department course-allocation document (.docx or .pdf).
    Matches rows against current timetable slots and assigns both the
    registered foreign-key lecturer and fallback lecturer_name_text.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [CanManageTimetable]

    def post(self, request, *args, **kwargs):
        if "file" not in request.FILES:
            return Response(
                {"detail": "No file provided in request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_obj = request.FILES["file"]
        _, ext = os.path.splitext(file_obj.name.lower())

        if ext not in VALID_ALLOCATION_EXTENSIONS:
            return Response(
                {"detail": f"Only .docx or .pdf files are supported. Got: {ext}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if ext == ".docx":
                tmp_path = f"/tmp/{file_obj.name}"
                with open(tmp_path, "wb") as f:
                    for chunk in file_obj.chunks():
                        f.write(chunk)
                try:
                    allocation_rows = parse_allocation_docx(tmp_path)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            else:
                allocation_rows = parse_allocation_pdf(file_obj)
        except Exception as e:
            return Response(
                {"detail": f"Could not parse file: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not allocation_rows:
            return Response(
                {"detail": "No valid allocation rows found in the document."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fall back to all slots if current term is unset or contains 0 records
        current_term = AcademicTerm.objects.filter(is_current=True).first()
        slot_qs = TimetableSlot.objects.all()
        if current_term and slot_qs.filter(term=current_term).exists():
            slot_qs = slot_qs.filter(term=current_term)

        results = []
        not_found = []

        for row in allocation_rows:
            unit_code = row.get("unit_code", "").strip()
            raw_code = row.get("raw_unit_code", unit_code).strip()
            lecturer_name = row.get("lecturer_name", "").strip()
            group_hint = row.get("group", "")

            # Generate normalization variants (e.g. 'COSC 104', 'COSC104', 'COSC 00104')
            compact_code = re.sub(r"[^A-Z0-9]", "", unit_code.upper())
            prefix_match = re.match(r"^([A-Z]+)(\d+)$", compact_code)

            query = Q(unit__code__iexact=unit_code) | Q(unit__code__iexact=compact_code)

            if prefix_match:
                dept_code, digits = prefix_match.groups()
                stripped_digits = digits.lstrip("0") or "0"
                query |= (Q(unit__code__icontains=dept_code) & Q(unit__code__icontains=stripped_digits))

            matched_slots_qs = slot_qs.filter(query)

            # If the row specifies a specific group (e.g. Group A / GRP K), narrow matches
            if group_hint:
                clean_group = group_hint.replace("GROUP", "").replace("GRP", "").strip()
                group_filtered = matched_slots_qs.filter(
                    Q(class_group__iexact=clean_group) |
                    Q(class_group__iexact=f"GR_{clean_group}") |
                    Q(class_group__iexact=f"GR {clean_group}")
                )
                if group_filtered.exists():
                    matched_slots_qs = group_filtered

            slots = list(matched_slots_qs)
            if not slots:
                not_found.append({
                    "unit_code": raw_code or unit_code,
                    "lecturer": lecturer_name,
                    "reason": "Unit not found in current timetable slots",
                })
                continue

            lecturer = _match_lecturer(lecturer_name)
            updated = 0

            for slot in slots:
                fields_to_update = []

                if lecturer and slot.lecturer_id != lecturer.id:
                    slot.lecturer = lecturer
                    fields_to_update.append("lecturer")

                if hasattr(slot, "lecturer_name_text"):
                    clean_display = re.sub(r"\(.*?\)", "", lecturer_name).strip()
                    if slot.lecturer_name_text != clean_display:
                        slot.lecturer_name_text = clean_display
                        fields_to_update.append("lecturer_name_text")

                if fields_to_update:
                    slot.save(update_fields=fields_to_update)
                    updated += 1

            results.append({
                "unit_code": raw_code or unit_code,
                "lecturer": lecturer_name,
                "account_linked": lecturer is not None,
                "slots_updated": updated,
            })

        slots_updated_total = sum(r["slots_updated"] for r in results)

        return Response({
            "detail": f"Processed {len(allocation_rows)} allocation row(s).",
            "matched": len(results),
            "unmatched": len(not_found),
            "slots_updated": slots_updated_total,
            "results": results,
            "not_found": not_found,
        })

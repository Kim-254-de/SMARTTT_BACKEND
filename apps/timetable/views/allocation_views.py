import os

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


def _match_lecturer(lecturer_name: str) -> Lecturer | None:
    """Case/whitespace-insensitive exact match against a Lecturer's full name."""
    target = " ".join(lecturer_name.split()).strip().lower()
    if not target:
        return None
    for lecturer in Lecturer.objects.select_related("user").all():
        if " ".join(lecturer.user.get_full_name().split()).strip().lower() == target:
            return lecturer
    return None


class AssignLecturersAPIView(APIView):
    """
    Upload a department course-allocation document (.docx or .pdf).
    Matches each row's unit code + lecturer name against the current
    term's timetable slots and the registered lecturers, then assigns
    the lecturer to every matching slot.
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
                # python-docx needs a real path
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
                {"detail": "No allocation rows found in the document."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_term = AcademicTerm.objects.filter(is_current=True).first()
        slot_qs = TimetableSlot.objects.filter(term=current_term) if current_term else TimetableSlot.objects.all()

        results = []
        not_found = []

        for row in allocation_rows:
            unit_code = row["unit_code"]
            lecturer_name = row["lecturer_name"]

            slots = list(slot_qs.filter(unit__code__iexact=unit_code))
            if not slots:
                not_found.append({
                    "unit_code": unit_code,
                    "lecturer": lecturer_name,
                    "reason": "Unit not found in the current timetable",
                })
                continue

            lecturer = _match_lecturer(lecturer_name)
            if not lecturer:
                not_found.append({
                    "unit_code": unit_code,
                    "lecturer": lecturer_name,
                    "reason": "Lecturer not registered (no matching account)",
                })
                continue

            updated = 0
            for slot in slots:
                if slot.lecturer_id != lecturer.id:
                    slot.lecturer = lecturer
                    slot.save(update_fields=["lecturer"])
                    updated += 1

            results.append({
                "unit_code": unit_code,
                "lecturer": lecturer_name,
                "account_linked": True,
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

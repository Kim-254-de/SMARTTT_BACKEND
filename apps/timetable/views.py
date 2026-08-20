from rest_framework import status
from rest_framework.generics import DestroyAPIView, ListAPIView, RetrieveAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import AcademicTerm, TimetableSlot, TimetableUpload, Unit
from .serializers import (
    AcademicTermSerializer, TimetableSlotSerializer,
    TimetableUploadSerializer, UnitSerializer,
)
from .services.upload_service import process_upload


class AcademicTermViewSet(ReadOnlyModelViewSet):
    queryset = AcademicTerm.objects.all()
    serializer_class = AcademicTermSerializer
    permission_classes = [IsAuthenticated]


class UnitViewSet(ReadOnlyModelViewSet):
    queryset = Unit.objects.select_related("department").all()
    serializer_class = UnitSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["department"]
    search_fields = ["code", "name"]


class TimetableSlotListView(ListAPIView):
    """Read-only master timetable — filterable by term, program, day."""
    serializer_class = TimetableSlotSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["term", "program", "day", "year_of_study"]

    def get_queryset(self):
        return TimetableSlot.objects.select_related(
            "term", "unit", "program", "lecturer__user", "room"
        ).all()


class TimetableUploadView(APIView):
    """
    POST /api/v1/timetable/upload/
    Admin uploads an Excel file. Processing happens synchronously.
    """
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=400)

        ext = file.name.rsplit(".", 1)[-1].lower()
        if ext not in ("xlsx", "xls", "csv", "pdf", "docx"):
            return Response(
                {"detail": "Only .xlsx, .xls, .csv, .pdf, or .docx files are accepted."},
                status=400,
            )

        upload = TimetableUpload.objects.create(
            uploaded_by=request.user,
            uploaded_file=file,
        )
        try:
            upload = process_upload(upload)
        except ImportError:
            return Response(
                {"detail": "PDF support is not installed on the server."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(TimetableUploadSerializer(upload).data, status=status.HTTP_201_CREATED)


class TimetableUploadDetailView(RetrieveAPIView):
    queryset = TimetableUpload.objects.all()
    serializer_class = TimetableUploadSerializer
    permission_classes = [IsAdminUser]
    lookup_field = "pk"


class TimetableUploadListView(ListAPIView):
    """GET /api/v1/timetable/upload/list/ — list all uploads, newest first."""
    queryset = TimetableUpload.objects.select_related("uploaded_by", "term").all()
    serializer_class = TimetableUploadSerializer
    permission_classes = [IsAdminUser]


class TimetableUploadDeleteView(DestroyAPIView):
    """
    DELETE /api/v1/timetable/upload/<uuid:pk>/delete/
    Deletes the upload record. Does NOT delete the TimetableSlot rows it created
    (those are shared/deduped across uploads via update_or_create) — only removes
    the audit record. To clear slots for a term, use the term-clear endpoint instead.
    """
    queryset = TimetableUpload.objects.all()
    permission_classes = [IsAdminUser]
    lookup_field = "pk"


class AcademicTermSetCurrentView(APIView):
    """
    POST /api/v1/timetable/terms/<uuid:pk>/set-current/
    Marks this term as current, unmarking all others.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({"detail": "Term not found."}, status=status.HTTP_404_NOT_FOUND)

        AcademicTerm.objects.filter(is_current=True).update(is_current=False)
        term.is_current = True
        term.save(update_fields=["is_current"])
        return Response({"detail": f"{term} is now the current term."})


class TimetableSlotsClearView(APIView):
    """
    DELETE /api/v1/timetable/terms/<uuid:pk>/clear-slots/
    Deletes all TimetableSlot rows for a given term — useful before re-uploading
    a corrected file for the same term.
    """
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({"detail": "Term not found."}, status=status.HTTP_404_NOT_FOUND)

        deleted_count, _ = TimetableSlot.objects.filter(term=term).delete()
        return Response({"detail": f"Deleted {deleted_count} slot(s) for {term}."})
        
"""
POST /api/v1/timetable/assign-lecturers/

Admin uploads the department allocation DOCX.
For each row:
  1. Find Unit by normalised unit_code
  2. Find or create Lecturer record by phone/name
  3. Update all TimetableSlot records for that unit in current term
  4. Add lecturer_name_text so students see name even before lecturer registers

Also adds lecturer_name_text field to TimetableSlot (migration needed).
"""
import os
import re
import tempfile

from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.timetable.models import AcademicTerm, TimetableSlot, Unit


def _normalise_code(code: str) -> str:
    return re.sub(r'\s+', '', code.upper().strip())


class AssignLecturersView(APIView):
    """
    POST /api/v1/timetable/assign-lecturers/
    Upload the department allocation DOCX to map lecturers to units.
    Accepts: .docx files only.
    """
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=400)

        ext = file.name.rsplit(".", 1)[-1].lower()
        if ext != "docx":
            return Response({"detail": "Only .docx files are accepted."}, status=400)

        # Save to temp file so python-docx can open it
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            from apps.timetable.services.allocation_parser import parse_allocation_docx
            rows = parse_allocation_docx(tmp_path)
        except Exception as exc:
            os.unlink(tmp_path)
            return Response({"detail": f"Could not parse file: {exc}"}, status=400)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        if not rows:
            return Response({"detail": "No unit-lecturer mappings found in document."}, status=400)

        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            return Response({"detail": "No current academic term set."}, status=400)

        # Build lookup: normalised_code → Unit
        all_units = {_normalise_code(u.code): u for u in Unit.objects.all()}

        matched = []
        unmatched = []
        slots_updated = 0

        for row in rows:
            norm_code = row["unit_code"]
            unit = all_units.get(norm_code)

            if not unit:
                unmatched.append({
                    "unit_code": row["unit_code_raw"],
                    "lecturer": row["lecturer_name"],
                    "reason": "Unit not found in master timetable",
                })
                continue

            # Try to find existing Lecturer profile by phone
            from apps.core.models import Lecturer
            from apps.accounts.models import User

            lecturer_profile = None

            # Match by phone number on User account
            phone = row["phone"]
            if phone:
                user = User.objects.filter(phone_number=phone).first()
                if user:
                    lecturer_profile, _ = Lecturer.objects.get_or_create(
                        user=user,
                        defaults={"department": unit.department, "title": ""},
                    )

            # Update TimetableSlots for this unit in current term
            slots = TimetableSlot.objects.filter(term=term, unit=unit)
            update_count = slots.update(
                lecturer=lecturer_profile,
                lecturer_name_text=row["lecturer_name"],
            )
            slots_updated += update_count

            matched.append({
                "unit_code": row["unit_code_raw"],
                "lecturer": row["lecturer_name"],
                "phone": row["phone"],
                "slots_updated": update_count,
                "account_linked": lecturer_profile is not None,
            })

        return Response({
            "detail": f"Processed {len(rows)} allocation rows.",
            "matched": len(matched),
            "unmatched": len(unmatched),
            "slots_updated": slots_updated,
            "results": matched,
            "not_found": unmatched,
        })

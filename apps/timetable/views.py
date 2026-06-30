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
        if ext not in ("xlsx", "xls", "csv"):
            return Response({"detail": "Only .xlsx, .xls, or .csv files are accepted."}, status=400)

        upload = TimetableUpload.objects.create(
            uploaded_by=request.user,
            uploaded_file=file,
        )
        upload = process_upload(upload)
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

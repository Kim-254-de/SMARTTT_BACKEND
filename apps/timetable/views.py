from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
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

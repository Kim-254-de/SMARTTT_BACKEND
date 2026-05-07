from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.timetable.models import AcademicTerm, TimetableConflict, TimetableSlot, TimetableUploadBatch
from apps.timetable.serializers import (
    AcademicTermSerializer,
    TimetableConflictSerializer,
    TimetableSlotSerializer,
    TimetableUploadBatchSerializer,
)
from apps.timetable.permissions import CanManageTimetable
from apps.timetable.services.upload_pipeline import TimetableUploadPipelineService


class AcademicTermViewSet(ModelViewSet):
    queryset = AcademicTerm.objects.all()
    serializer_class = AcademicTermSerializer
    permission_classes = [CanManageTimetable]
    filterset_fields = ["academic_year", "semester", "is_current"]


class TimetableSlotViewSet(ModelViewSet):
    queryset = TimetableSlot.objects.select_related(
        "term", "curriculum_unit", "lecturer", "room"
    ).all()
    serializer_class = TimetableSlotSerializer
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "day_of_week", "room", "lecturer"]


class TimetableConflictViewSet(ReadOnlyModelViewSet):
    queryset = TimetableConflict.objects.select_related("term", "slot_a", "slot_b").all()
    serializer_class = TimetableConflictSerializer
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "conflict_type"]


class TimetableUploadAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [CanManageTimetable]

    def post(self, request, *args, **kwargs):
        if "file" not in request.FILES:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        file_obj = request.FILES["file"]
        serializer = TimetableUploadBatchSerializer(
            data={"uploaded_by": request.user.id, "source_file": file_obj}
        )
        serializer.is_valid(raise_exception=True)
        upload_batch = serializer.save()

        result = TimetableUploadPipelineService().execute(upload_batch=upload_batch)
        response_status = status.HTTP_201_CREATED if result["success"] else status.HTTP_400_BAD_REQUEST
        return Response(result, status=response_status)

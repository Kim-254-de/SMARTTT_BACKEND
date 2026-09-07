import os
import uuid
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.pagination import PageNumberPagination

from apps.timetable.models import (
    AcademicTerm,
    TimetableConflict,
    TimetableSlot,
    TimetableUploadBatch,
)
from apps.timetable.serializers import (
    AcademicTermSerializer,
    TimetableConflictSerializer,
    ConflictDetailSerializer,
    TimetableSlotSerializer,
    TimetableSlotDetailedSerializer,
    TimetableUploadBatchSerializer,
    TimetableUploadBatchDetailedSerializer,
)
from apps.timetable.permissions import CanManageTimetable
from apps.timetable.services.background_worker import dispatch_async_upload
from apps.timetable.validators import ExcelFileValidator
from apps.timetable.utils import TimetableResponseFormatter


# Keep StandardResultsSetPagination, AcademicTermViewSet, TimetableSlotViewSet, 
# TimetableConflictViewSet, and TimetableUploadListViewSet as they are...


class TimetableUploadAPIView(APIView):
    """
    Receives timetable files (.pdf, .xlsx, etc.) and starts 
    background parsing immediately, returning HTTP 202 Accepted.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [CanManageTimetable]

    def post(self, request, *args, **kwargs):
        if "file" not in request.FILES:
            return Response(
                TimetableResponseFormatter.error_response(
                    error_code="NO_FILE_PROVIDED",
                    error_message="No file provided in request.",
                    details=["Provide a timetable file in the 'file' field."]
                ),
                status=status.HTTP_400_BAD_REQUEST
            )

        file_obj = request.FILES["file"]

        # Validate file size & extension (PDFs/Excels)
        try:
            ExcelFileValidator.validate_file_extension(file_obj.name)
            ExcelFileValidator.validate_file_size(file_obj.size)
        except Exception as e:
            return Response(
                TimetableResponseFormatter.error_response(
                    error_code="FILE_VALIDATION_ERROR",
                    error_message="File validation failed",
                    details=[str(e)]
                ),
                status=status.HTTP_400_BAD_REQUEST
            )

        # Save the file to disk for background thread access
        temp_dir = os.path.join(settings.BASE_DIR, "tmp_uploads")
        os.makedirs(temp_dir, exist_ok=True)
        unique_file_name = f"{uuid.uuid4()}_{file_obj.name}"
        saved_file_path = os.path.join(temp_dir, unique_file_name)

        with open(saved_file_path, "wb+") as dest:
            for chunk in file_obj.chunks():
                dest.write(chunk)

        # Create batch record with 'processing' status
        serializer = TimetableUploadBatchSerializer(
            data={"uploaded_by": request.user.id, "source_file": file_obj}
        )
        if not serializer.is_valid():
            return Response(
                TimetableResponseFormatter.error_response(
                    error_code="BATCH_CREATION_ERROR",
                    error_message="Failed to create upload batch",
                    details=[str(v[0]) for v in serializer.errors.values()]
                ),
                status=status.HTTP_400_BAD_REQUEST
            )

        upload_batch = serializer.save(status="processing")
        academic_year = request.data.get("academic_year", "2026/2027")

        # Spawn daemon worker thread
        dispatch_async_upload(upload_batch, saved_file_path, academic_year=academic_year)

        # Return 202 Accepted within <500ms to avoid 504 timeouts
        return Response(
            {
                "status": "processing",
                "message": "Upload accepted and processing in background.",
                "upload_batch_id": str(upload_batch.id),
                "batch_id": str(upload_batch.id),
            },
            status=status.HTTP_202_ACCEPTED
        )


class TimetableUploadStatusAPIView(APIView):
    """
    Polled by admin.html to check ingestion progress.
    """
    permission_classes = [CanManageTimetable]

    def get(self, request, batch_id, *args, **kwargs):
        try:
            batch = TimetableUploadBatch.objects.get(id=batch_id)
        except TimetableUploadBatch.DoesNotExist:
            return Response(
                {"detail": "Upload batch not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            "upload_batch_id": str(batch.id),
            "status": batch.status,
            "rows_received": batch.rows_received,
            "rows_saved": batch.rows_saved,
            "rows_failed": batch.rows_failed,
        }, status=status.HTTP_200_OK)

from __future__ import annotations

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
    TimetableSlotRescheduleSerializer,
    TimetableUploadBatchSerializer,
    TimetableUploadBatchDetailedSerializer,
)
from apps.timetable.permissions import CanManageTimetable, CanRescheduleTimetableSlot
from apps.timetable.services.background_worker import dispatch_async_upload
from apps.timetable.services.reschedule_notifications import notify_students_of_reschedule
from apps.timetable.validators import ExcelFileValidator
from apps.timetable.utils import TimetableResponseFormatter


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for list endpoints."""
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class AcademicTermViewSet(ModelViewSet):
    queryset = AcademicTerm.objects.all()
    serializer_class = AcademicTermSerializer
    permission_classes = [CanManageTimetable]
    filterset_fields = ["academic_year", "semester", "is_current"]
    ordering_fields = ["-academic_year", "-semester", "is_current"]
    ordering = ["-academic_year", "-semester"]
    pagination_class = StandardResultsSetPagination

    @action(detail=True, methods=["delete"], url_path="clear-slots")
    def clear_slots(self, request, pk=None):
        term = self.get_object()
        deleted_count, _ = TimetableSlot.objects.filter(term=term).delete()
        return Response(
            {"detail": f"Deleted {deleted_count} slot(s) for this term."},
            status=status.HTTP_200_OK,
        )


class TimetableSlotViewSet(ModelViewSet):
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "day_of_week", "room", "lecturer", "upload_batch", "unit"]
    ordering_fields = ["term", "_day_sort", "start_time", "end_time"]
    ordering = ["term", "_day_sort", "start_time"]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        from apps.timetable.utils.day_order import day_of_week_sort_case
        return TimetableSlot.objects.select_related(
            "term",
            "unit",
            "program",
            "lecturer",
            "lecturer__user",
            "room",
            "upload_batch",
            "upload_batch__uploaded_by"
        ).annotate(_day_sort=day_of_week_sort_case()).order_by("term", "_day_sort", "start_time")

    def get_serializer_class(self):
        if self.action == "detailed":
            return TimetableSlotDetailedSerializer
        if self.action == "reschedule":
            return TimetableSlotRescheduleSerializer
        return TimetableSlotSerializer

    def get_permissions(self):
        # `reschedule` is deliberately open to the owning lecturer, unlike
        # every other action on this viewset which stays admin-only
        # (create/update/delete a slot's unit, program, lecturer, etc.).
        if self.action == "reschedule":
            return [CanRescheduleTimetableSlot()]
        return super().get_permissions()

    @action(detail=True, methods=["get"])
    def detailed(self, request, pk=None):
        slot = self.get_object()
        serializer = TimetableSlotDetailedSerializer(slot)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """
        POST /api/v1/timetable/slots/{id}/reschedule/
        Body: { "day_of_week"?, "start_time"?, "end_time"?, "room"?, "reason"? }

        Moves a class to a new day/time/room. Callable by admins/registrar/
        department admins for any slot, or by a lecturer for a slot they
        teach. Rejects the change if it collides with another class already
        booked in that room at the new day/time, and — on success — notifies
        every student enrolled in the unit this term.
        """
        slot = self.get_object()  # runs CanRescheduleTimetableSlot.has_object_permission

        serializer = TimetableSlotRescheduleSerializer(instance=slot, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        new_day = data.get("day_of_week", slot.day_of_week)
        new_start = data.get("start_time", slot.start_time)
        new_end = data.get("end_time", slot.end_time)
        new_room = data.get("room", slot.room)
        reason = data.get("reason", "")

        conflict = (
            TimetableSlot.objects.filter(term=slot.term_id, day_of_week=new_day, room=new_room)
            .exclude(pk=slot.pk)
            .filter(start_time__lt=new_end, end_time__gt=new_start)
            .select_related("unit")
            .first()
        )
        if conflict:
            return Response(
                {
                    "detail": (
                        f"{new_room.code} is already booked on "
                        f"{conflict.get_day_of_week_display()} "
                        f"{conflict.start_time:%H:%M}-{conflict.end_time:%H:%M} "
                        f"for {conflict.unit.code if conflict.unit else 'another class'}."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        old_day, old_start, old_end, old_room = (
            slot.day_of_week, slot.start_time, slot.end_time, slot.room,
        )

        slot.day_of_week = new_day
        slot.start_time = new_start
        slot.end_time = new_end
        slot.room = new_room
        slot.save(update_fields=["day_of_week", "start_time", "end_time", "room", "updated_at"])

        notify_result = notify_students_of_reschedule(
            slot,
            old_day=old_day,
            old_start=old_start,
            old_end=old_end,
            old_room=old_room,
            reason=reason,
            sent_by=request.user,
        )

        return Response(
            {
                "slot": TimetableSlotDetailedSerializer(slot).data,
                "notified": notify_result,
            }
        )


class TimetableConflictViewSet(ReadOnlyModelViewSet):
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "conflict_type", "slot_a", "slot_b"]
    ordering_fields = ["created_at", "conflict_type"]
    ordering = ["-created_at"]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return TimetableConflict.objects.select_related(
            "term",
            "slot_a",
            "slot_a__unit",
            "slot_a__room",
            "slot_a__lecturer",
            "slot_b",
            "slot_b__unit",
            "slot_b__room",
            "slot_b__lecturer"
        ).all()

    def get_serializer_class(self):
        return ConflictDetailSerializer


class TimetableUploadListViewSet(ReadOnlyModelViewSet):
    permission_classes = [CanManageTimetable]
    filterset_fields = ["status", "uploaded_by"]
    ordering_fields = ["created_at", "status", "rows_saved"]
    ordering = ["-created_at"]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return TimetableUploadBatch.objects.select_related(
            "uploaded_by"
        ).all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TimetableUploadBatchDetailedSerializer
        return TimetableUploadBatchSerializer


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

        # Validate file size & extension
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

        # Save temporary file on server disk
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


class TimetableUploadDeleteAPIView(APIView):
    """
    Deletes an upload batch's audit record only. TimetableSlot.upload_batch
    uses on_delete=SET_NULL, so slots created by this batch are untouched.
    """
    permission_classes = [CanManageTimetable]

    def delete(self, request, batch_id, *args, **kwargs):
        try:
            batch = TimetableUploadBatch.objects.get(id=batch_id)
        except TimetableUploadBatch.DoesNotExist:
            return Response(
                {"detail": "Upload batch not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        batch.delete()
        return Response(
            {"detail": "Upload record deleted."},
            status=status.HTTP_200_OK
        )

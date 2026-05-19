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
from apps.timetable.services.upload_pipeline import TimetableUploadPipelineService
from apps.timetable.validators import ExcelFileValidator
from apps.timetable.utils import (
    TimetableResponseFormatter,
    FileValidationException,
)


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for list endpoints."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


class AcademicTermViewSet(ModelViewSet):
    queryset = AcademicTerm.objects.all()
    serializer_class = AcademicTermSerializer
    permission_classes = [CanManageTimetable]
    filterset_fields = ["academic_year", "semester", "is_current"]
    ordering_fields = ["-academic_year", "-semester", "is_current"]
    ordering = ["-academic_year", "-semester"]
    pagination_class = StandardResultsSetPagination


class TimetableSlotViewSet(ModelViewSet):
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "day_of_week", "room", "lecturer", "upload_batch"]
    ordering_fields = ["term", "day_of_week", "start_time", "end_time"]
    ordering = ["term", "day_of_week", "start_time"]
    pagination_class = StandardResultsSetPagination
    
    def get_queryset(self):
        """Get optimized queryset with proper select_related."""
        return TimetableSlot.objects.select_related(
            "term",
            "curriculum_unit",
            "curriculum_unit__curriculum",
            "curriculum_unit__unit",
            "lecturer",
            "lecturer__user",
            "room",
            "upload_batch",
            "upload_batch__uploaded_by"
        ).all()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'detailed':
            return TimetableSlotDetailedSerializer
        return TimetableSlotSerializer
    
    @action(detail=True, methods=['get'])
    def detailed(self, request, pk=None):
        """Get detailed slot information with all related data."""
        slot = self.get_object()
        serializer = TimetableSlotDetailedSerializer(slot)
        return Response(serializer.data)


class TimetableConflictViewSet(ReadOnlyModelViewSet): 
    permission_classes = [CanManageTimetable]
    filterset_fields = ["term", "conflict_type", "slot_a", "slot_b"]
    ordering_fields = ["created_at", "conflict_type"]
    ordering = ["-created_at"]
    pagination_class = StandardResultsSetPagination
    
    def get_queryset(self):
        """Get optimized queryset with proper select_related."""
        return TimetableConflict.objects.select_related(
            "term",
            "slot_a",
            "slot_a__curriculum_unit",
            "slot_a__room",
            "slot_a__lecturer",
            "slot_b",
            "slot_b__curriculum_unit",
            "slot_b__room",
            "slot_b__lecturer"
        ).all()
    
    def get_serializer_class(self):
        """Use detailed serializer for conflict responses."""
        return ConflictDetailSerializer


class TimetableUploadListViewSet(ReadOnlyModelViewSet):
    permission_classes = [CanManageTimetable]
    filterset_fields = ["status", "uploaded_by"]
    ordering_fields = ["created_at", "status", "rows_saved"]
    ordering = ["-created_at"]
    pagination_class = StandardResultsSetPagination
    
    def get_queryset(self):
        """Get optimized queryset with proper select_related."""
        return TimetableUploadBatch.objects.select_related(
            "uploaded_by"
        ).all()
    
    def get_serializer_class(self):
        """Return detailed serializer with nested slots."""
        if self.action == 'retrieve':
            return TimetableUploadBatchDetailedSerializer
        return TimetableUploadBatchSerializer


class TimetableUploadAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [CanManageTimetable]
    
    def post(self, request, *args, **kwargs):
        """
        Handle timetable file upload.
        
        Args:
            request: HTTP request with file
            
        Returns:
            Response with upload report
        """
        try:
            # Validate file is provided
            if "file" not in request.FILES:
                return Response(
                    TimetableResponseFormatter.error_response(
                        error_code="NO_FILE_PROVIDED",
                        error_message="No file provided in request.",
                        details=["Provide Excel file in 'file' field"]
                    ),
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            file_obj = request.FILES["file"]
            
            # Validate file extension and size
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
            
            # Create upload batch
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
            
            upload_batch = serializer.save()
            
            # Execute upload pipeline
            pipeline_service = TimetableUploadPipelineService()
            result = pipeline_service.execute(upload_batch=upload_batch)
            
            # Determine response status based on result
            if result["status"] == "success":
                response_status = status.HTTP_201_CREATED
            elif result["status"] == "partial":
                response_status = status.HTTP_200_OK
            else:
                response_status = status.HTTP_400_BAD_REQUEST
            
            return Response(result, status=response_status)
            
        except Exception as e:
            return Response(
                TimetableResponseFormatter.error_response(
                    error_code="UPLOAD_PROCESSING_ERROR",
                    error_message="An error occurred during upload processing",
                    details=[str(e)]
                ),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


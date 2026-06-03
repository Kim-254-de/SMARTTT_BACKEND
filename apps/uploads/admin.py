from django.contrib import admin

from apps.uploads.models import TimetableUpload, UploadConflictReport, UploadProcessingLog


@admin.register(TimetableUpload)
class TimetableUploadAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "uploaded_by", "department", "processing_status", "total_rows", "successful_rows", "failed_rows", "uploaded_at")
    list_filter = ("processing_status", "department", "uploaded_at")
    search_fields = ("original_filename", "uploaded_by__username", "uploaded_by__university_id")
    readonly_fields = ("uploaded_at", "processed_at")

    def save_model(self, request, obj, form, change):
        if not hasattr(obj, 'uploaded_by') or not obj.uploaded_by:
            obj.uploaded_by = request.user
        if not obj.original_filename and obj.uploaded_file:
            obj.original_filename = obj.uploaded_file.name
        super().save_model(request, obj, form, change)
        
        # Trigger parsing and processing immediately
        from apps.uploads.services import UploadProcessingService
        UploadProcessingService.process_upload(upload=obj)


@admin.register(UploadProcessingLog)
class UploadProcessingLogAdmin(admin.ModelAdmin):
    list_display = ("upload", "row_number", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("upload__original_filename", "error_message")


@admin.register(UploadConflictReport)
class UploadConflictReportAdmin(admin.ModelAdmin):
    list_display = ("upload", "conflict_type", "severity", "created_at")
    list_filter = ("conflict_type", "severity", "created_at")
    search_fields = ("upload__original_filename", "description")
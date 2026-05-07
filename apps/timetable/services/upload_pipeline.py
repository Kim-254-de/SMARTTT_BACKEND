from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.timetable.models import TimetableUploadBatch
from apps.timetable.services.conflict_detector import TimetableConflictDetectionService
from apps.timetable.services.excel_parser import TimetableExcelParserService
from apps.timetable.services.persistence import TimetablePersistenceService
from apps.timetable.services.transformer import TimetableTransformService
from apps.timetable.validators.upload_validator import TimetableUploadValidator


class TimetableUploadPipelineService:
    @transaction.atomic
    def execute(self, upload_batch: TimetableUploadBatch):
        try:
            parser = TimetableExcelParserService()
            dataframe = parser.parse(upload_batch.source_file.path)
            upload_batch.rows_received = len(dataframe.index)

            TimetableUploadValidator.validate_columns(dataframe.columns)

            transformer = TimetableTransformService()
            transformed_rows = [transformer.transform_row(row) for _, row in dataframe.iterrows()]

            persistence = TimetablePersistenceService()
            saved_slots = persistence.save_rows(upload_batch=upload_batch, rows=transformed_rows)

            conflict_service = TimetableConflictDetectionService()
            conflicts = conflict_service.detect(saved_slots)

            upload_batch.status = TimetableUploadBatch.Status.PROCESSED
            upload_batch.rows_saved = len(saved_slots)
            upload_batch.save(update_fields=["rows_received", "rows_saved", "status", "updated_at"])

            return {
                "success": True,
                "upload_batch_id": str(upload_batch.id),
                "rows_received": upload_batch.rows_received,
                "rows_saved": upload_batch.rows_saved,
                "conflicts_detected": len(conflicts),
            }
        except Exception as exc:
            upload_batch.status = TimetableUploadBatch.Status.FAILED
            upload_batch.validation_errors = [str(exc)]
            upload_batch.save(update_fields=["status", "validation_errors", "updated_at"])
            return {
                "success": False,
                "upload_batch_id": str(upload_batch.id),
                "errors": upload_batch.validation_errors,
            }

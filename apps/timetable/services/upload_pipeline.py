from typing import Dict, Any
from django.db import transaction

from apps.timetable.models import TimetableUploadBatch
from apps.timetable.services.conflict_detector import TimetableConflictDetectionService
from apps.timetable.services.file_dispatcher import parse_timetable_file
from apps.timetable.services.persistence import TimetablePersistenceService
from apps.timetable.services.transformer import TimetableTransformService
from apps.timetable.validators import (
    TimetableUploadValidator,
    TimetableDataConsistencyValidator,
)
from apps.timetable.utils import (
    TimetableLogger,
    TimetableResponseFormatter,
    ResponseStatus,
    ExcelParsingException,
    DataValidationException,
    DatabaseOperationException,
)


class TimetableUploadPipelineService: 
    def __init__(self):
        """Initialize pipeline with required services."""
        self.transform_service = TimetableTransformService()
        self.persistence_service = TimetablePersistenceService()
        self.conflict_service = TimetableConflictDetectionService()
        self.logger = TimetableLogger()
    
    @transaction.atomic
    def execute(self, upload_batch: TimetableUploadBatch) -> Dict[str, Any]:
        try:
            # Log upload start
            self.logger.log_upload_started(
                upload_batch.id,
                upload_batch.source_file.name
            )
            
            # Stage 1: Parse the uploaded file (xlsx/xls/csv/pdf/docx)
            raw_rows = parse_timetable_file(upload_batch.source_file.path)
            rows_received = len(raw_rows)
            upload_batch.rows_received = rows_received
            
            # Stage 2: Validate columns
            if raw_rows:
                TimetableUploadValidator.validate_columns(raw_rows[0].keys())
            
            # Stage 3: (rows already extracted by the parser)
            self.logger.log_parsing_started(upload_batch.id, rows_received)
            parse_errors = []
            
            # Stage 4: Validate rows
            validation_errors = []
            valid_rows = []
            
            for idx, row in enumerate(raw_rows):
                is_valid, errors = TimetableUploadValidator.validate_row(row, idx + 2)
                if not is_valid:
                    validation_errors.extend(errors)
                    self.logger.log_validation_error(
                        upload_batch.id,
                        idx + 2,
                        "row",
                        "; ".join(errors)
                    )
                else:
                    valid_rows.append(row)
            
            # Add parsing errors to validation errors
            if parse_errors:
                for error in parse_errors:
                    msg = f"Row {error['row_number']}: {error['error']}"
                    validation_errors.append(msg)
                    self.logger.log_validation_error(
                        upload_batch.id,
                        error['row_number'],
                        "parse",
                        error['error']
                    )
            
            # Check for duplicate rows
            duplicates_found, duplicate_details = TimetableDataConsistencyValidator.validate_no_duplicate_sessions(valid_rows)
            if not duplicates_found:
                for dup in duplicate_details:
                    msg = f"Row {dup['duplicate_at_row']}: Duplicate of row {dup['first_occurrence']}"
                    validation_errors.append(msg)
                    self.logger.log_validation_error(
                        upload_batch.id,
                        dup['duplicate_at_row'],
                        "duplicate",
                        msg
                    )
                    # Remove duplicate from valid rows
                    valid_rows = [r for r in valid_rows if r not in [dup['data']]]
            
            # If no valid rows remain, report error
            if not valid_rows:
                upload_batch.status = TimetableUploadBatch.Status.FAILED
                upload_batch.validation_errors = validation_errors
                upload_batch.rows_saved = 0
                upload_batch.save(update_fields=["status", "validation_errors", "rows_saved", "updated_at"])
                
                self.logger.log_upload_failed(
                    upload_batch.id,
                    "No valid rows to process",
                    len(raw_rows)
                )
                
                return TimetableResponseFormatter.upload_response(
                    upload_batch_id=str(upload_batch.id),
                    rows_received=rows_received,
                    rows_saved=0,
                    rows_failed=len(raw_rows),
                    validation_errors=validation_errors,
                    status=ResponseStatus.ERROR,
                )
            
            # Stage 5: Transform valid rows
            transformed_rows, transform_errors = self.transform_service.transform_rows(valid_rows)
            
            if transform_errors:
                for error in transform_errors:
                    validation_errors.append(
                        f"Row {error['row_number']}: {error['error']}"
                    )
            
            if not transformed_rows:
                upload_batch.status = TimetableUploadBatch.Status.FAILED
                upload_batch.validation_errors = validation_errors
                upload_batch.rows_saved = 0
                upload_batch.save(update_fields=["status", "validation_errors", "rows_saved", "updated_at"])
                
                return TimetableResponseFormatter.upload_response(
                    upload_batch_id=str(upload_batch.id),
                    rows_received=rows_received,
                    rows_saved=0,
                    rows_failed=len(raw_rows),
                    validation_errors=validation_errors,
                    status=ResponseStatus.ERROR,
                )
            
            # Stage 6: Persist data to database
            saved_slots, persistence_errors = self.persistence_service.save_rows(
                upload_batch=upload_batch,
                rows=transformed_rows
            )
            
            # Combine all errors
            if persistence_errors:
                validation_errors.extend([
                    f"Row {e['row_number']}: {e['error']}"
                    for e in persistence_errors
                ])
            
            rows_saved = len(saved_slots)
            rows_failed = rows_received - rows_saved
            
            # Stage 7: Detect conflicts
            conflicts_detected = 0
            if saved_slots:
                conflicts = self.conflict_service.detect(saved_slots)
                conflicts_detected = len(conflicts)
            
            # Stage 8: Update upload batch status
            upload_batch.status = TimetableUploadBatch.Status.PROCESSED
            upload_batch.rows_saved = rows_saved
            upload_batch.validation_errors = validation_errors
            upload_batch.save(update_fields=["status", "rows_saved", "validation_errors", "updated_at"])
            
            # Log successful upload
            self.logger.log_upload_completed(
                upload_batch.id,
                rows_received,
                rows_saved,
                conflicts_detected
            )
            
            # Generate response
            response_status = ResponseStatus.SUCCESS if rows_failed == 0 else ResponseStatus.PARTIAL
            
            return TimetableResponseFormatter.upload_response(
                upload_batch_id=str(upload_batch.id),
                rows_received=rows_received,
                rows_saved=rows_saved,
                rows_failed=rows_failed,
                validation_errors=validation_errors,
                conflicts_detected=conflicts_detected,
                status=response_status,
            )
            
        except (ExcelParsingException, DataValidationException, DatabaseOperationException) as e:
            # Expected exceptions - log and return error response
            upload_batch.status = TimetableUploadBatch.Status.FAILED
            upload_batch.validation_errors = [str(e)]
            upload_batch.save(update_fields=["status", "validation_errors", "updated_at"])
            
            self.logger.log_upload_failed(
                upload_batch.id,
                str(e),
                upload_batch.rows_received
            )
            
            return TimetableResponseFormatter.upload_response(
                upload_batch_id=str(upload_batch.id),
                rows_received=upload_batch.rows_received,
                rows_saved=0,
                rows_failed=upload_batch.rows_received,
                validation_errors=[str(e)],
                status=ResponseStatus.ERROR,
            )
        
        except Exception as e:
            # Unexpected exceptions - log as error
            upload_batch.status = TimetableUploadBatch.Status.FAILED
            error_msg = f"Unexpected error during upload processing: {str(e)}"
            upload_batch.validation_errors = [error_msg]
            upload_batch.save(update_fields=["status", "validation_errors", "updated_at"])
            
            self.logger.log_upload_failed(
                upload_batch.id,
                error_msg,
                upload_batch.rows_received
            )
            
            return TimetableResponseFormatter.upload_response(
                upload_batch_id=str(upload_batch.id),
                rows_received=upload_batch.rows_received,
                rows_saved=0,
                rows_failed=upload_batch.rows_received,
                validation_errors=[error_msg],
                status=ResponseStatus.ERROR,
            )


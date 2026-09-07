import os
import threading
import logging
from django.db import connection
from apps.timetable.models import TimetableUploadBatch
from apps.timetable.services.pdf_timetable_parser import parse_pdf, to_timetable_slot_dicts
from apps.timetable.services.persistence import TimetablePersistenceService

logger = logging.getLogger(__name__)

def _process_timetable_async(batch_id: str, file_path: str, academic_year: str = "2026/2027"):
    """
    Background worker function executed in an isolated thread.
    Ensures database connection isolation and safe status updates.
    """
    # Close old connection to avoid thread-sharing issues with Django's connection pool
    connection.close()

    try:
        batch = TimetableUploadBatch.objects.get(id=batch_id)
    except TimetableUploadBatch.DoesNotExist:
        logger.error(f"Upload batch {batch_id} not found.")
        return

    try:
        # 1. Parse PDF
        logger.info(f"[Batch {batch_id}] Parsing PDF at {file_path}")
        parse_result = parse_pdf(file_path)
        
        # 2. Normalize dictionaries
        slot_dicts = to_timetable_slot_dicts(parse_result, academic_year=academic_year)
        batch.rows_received = len(slot_dicts)
        batch.save(update_fields=["rows_received"])

        # 3. Persist rows into Supabase
        persistence = TimetablePersistenceService()
        saved_slots, errors = persistence.save_rows(upload_batch=batch, rows=slot_dicts)

        # 4. Finalize batch status
        batch.rows_saved = len(saved_slots)
        batch.rows_failed = len(errors)
        batch.status = "processed" if not errors else "partial"
        batch.save(update_fields=["rows_saved", "rows_failed", "status"])
        logger.info(f"[Batch {batch_id}] Finished: {len(saved_slots)} saved, {len(errors)} failed.")

    except Exception as exc:
        logger.exception(f"[Batch {batch_id}] Extraction crashed: {exc}")
        batch.status = "failed"
        batch.save(update_fields=["status"])
    finally:
        # Cleanup temporary uploaded file if desired
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        connection.close()


def dispatch_async_upload(batch: TimetableUploadBatch, file_path: str, academic_year: str = "2026/2027"):
    """Spawns an asynchronous daemon thread to run the parsing task."""
    worker_thread = threading.Thread(
        target=_process_timetable_async,
        args=(str(batch.id), file_path, academic_year),
        daemon=True,
    )
    worker_thread.start()

"""
Memory-efficient streaming timetable upload service.

Handles large PDF/Excel files using:
- Streaming/chunking instead of loading entire file into memory
- Batch inserts with configurable batch sizes
- Database-level deduplication with update_or_create
- Progress tracking and detailed error reporting
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable, Optional

from django.db import transaction
from django.utils import timezone

from apps.timetable.models import AcademicTerm, TimetableSlot, TimetableUploadBatch
from apps.timetable.services.docx_timetable_parser import parse_docx
from apps.timetable.services.excel_parser import parse_excel
from apps.timetable.services.pdf_timetable_parser import (
    parse_pdf,
    parse_pdf_streaming,
    to_timetable_slot_dicts,
)
from apps.timetable.services.mapper import (
    resolve_department,
    resolve_lecturer,
    resolve_program,
    resolve_room,
    resolve_time,
    resolve_unit,
)


BATCH_SIZE = 100  # Process 100 slots at a time to balance memory vs DB hits
SLOT_BATCH_INSERT_SIZE = 50  # Insert 50 slots per bulk_create call


def _get_or_create_term(academic_year: str, semester: int) -> AcademicTerm:
    """Get or create an academic term."""
    term, _ = AcademicTerm.objects.get_or_create(
        academic_year=academic_year,
        semester=semester,
        defaults={
            "start_date": timezone.now().date(),
            "end_date": timezone.now().date(),
            "is_current": False,
        },
    )
    return term


def _process_row_to_slot(row: dict) -> tuple[TimetableSlot | None, Optional[str]]:
    """
    Convert a parsed row dict to a TimetableSlot model instance.
    Returns (slot, error_message) tuple.
    """
    try:
        department = resolve_department(row)
        program = resolve_program(row, department)
        unit = resolve_unit(row, department)
        if not unit:
            return None, "Unit code is missing or unresolvable"

        room = resolve_room(row)
        lecturer = resolve_lecturer(row, department)
        start_time, end_time = resolve_time(row)
        if not start_time or not end_time:
            return None, "Start time and end time are required"

        day = str(row.get("day") or "").upper()
        if day not in [c.value for c in TimetableSlot.WeekDay]:
            return None, f"Invalid day value: {day!r}"

        academic_year = str(row.get("academic_year") or "2026/2027").strip()
        semester = int(row.get("semester") or 1)
        year_of_study = int(row.get("year_of_study") or 1)
        term = _get_or_create_term(academic_year, semester)

        return (
            TimetableSlot(
                term=term,
                unit=unit,
                program=program,
                year_of_study=year_of_study,
                lecturer=lecturer,
                room=room,
                day=day,
                start_time=start_time,
                end_time=end_time,
                class_group=row.get("class_group", "MAIN"),
                upload_batch=None,  # Will be set after successful creation
            ),
            None,
        )
    except Exception as exc:
        return None, str(exc)


def process_upload_streaming(
    upload: TimetableUploadBatch,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> TimetableUploadBatch:
    """
    Process timetable upload using streaming approach for memory efficiency.

    Args:
        upload: TimetableUploadBatch instance with uploaded_file
        progress_callback: Optional callback(rows_processed, rows_saved, status_msg)
                          for progress tracking

    Returns:
        Updated TimetableUploadBatch with status, counts, and errors
    """
    upload.status = TimetableUploadBatch.Status.VALIDATED
    upload.save(update_fields=["status"])

    ext = os.path.splitext(upload.source_file.name)[1].lower().lstrip(".")
    errors = []
    rows_received = 0
    rows_saved = 0

    # Determine parser based on file type
    if ext in ("xlsx", "xls", "csv"):
        # Excel/CSV parsers return full list (not streaming)
        # Future: could optimize Excel parser similarly
        try:
            rows_data = parse_excel(upload.source_file)
            row_iterator = iter(rows_data)
        except ValueError as exc:
            upload.status = TimetableUploadBatch.Status.FAILED
            upload.validation_errors = [{"row": 0, "error": str(exc)}]
            upload.save(update_fields=["status", "validation_errors"])
            return upload

    elif ext == "pdf":
        # Use streaming PDF parser for memory efficiency
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                for chunk in upload.source_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            # Create streaming iterator from PDF
            def pdf_stream_generator():
                """Generator that yields rows from PDF slots."""
                for slot_batch, page, table_idx in parse_pdf_streaming(
                    tmp_path, chunk_size=BATCH_SIZE
                ):
                    if page == -1:
                        # Sentinel value indicating end
                        break
                    # Convert RawSlot objects to row dicts
                    slot_dicts = to_timetable_slot_dicts_from_batch(slot_batch)
                    for row_dict in slot_dicts:
                        yield row_dict

            row_iterator = pdf_stream_generator()

        except Exception as exc:
            upload.status = TimetableUploadBatch.Status.FAILED
            upload.validation_errors = [{"row": 0, "error": f"PDF parsing error: {str(exc)}"}]
            upload.save(update_fields=["status", "validation_errors"])
            return upload
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    elif ext == "docx":
        try:
            tmp_path = None
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                for chunk in upload.source_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            rows_data = parse_docx(tmp_path)
            row_iterator = iter(rows_data)
        except Exception as exc:
            upload.status = TimetableUploadBatch.Status.FAILED
            upload.validation_errors = [{"row": 0, "error": f"DOCX parsing error: {str(exc)}"}]
            upload.save(update_fields=["status", "validation_errors"])
            return upload
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    else:
        upload.status = TimetableUploadBatch.Status.FAILED
        upload.validation_errors = [{"row": 0, "error": f"Unsupported file type: .{ext}"}]
        upload.save(update_fields=["status", "validation_errors"])
        return upload

    # Process rows in batches
    batch_buffer = []
    row_num = 1

    try:
        with transaction.atomic():
            for row_num, row_data in enumerate(row_iterator, start=2):
                rows_received += 1

                slot, error = _process_row_to_slot(row_data)
                if error:
                    errors.append({"row": row_num, "error": error})
                    continue

                batch_buffer.append(slot)

                # Process batch when size reached
                if len(batch_buffer) >= SLOT_BATCH_INSERT_SIZE:
                    saved_count = _save_slot_batch(
                        batch_buffer, upload, errors, row_num
                    )
                    rows_saved += saved_count
                    batch_buffer = []

                    if progress_callback:
                        progress_callback(
                            rows_received,
                            rows_saved,
                            f"Processed {rows_received} rows, saved {rows_saved}"
                        )

            # Save final batch
            if batch_buffer:
                saved_count = _save_slot_batch(batch_buffer, upload, errors, row_num)
                rows_saved += saved_count

    except Exception as exc:
        errors.append({"row": 0, "error": f"Transaction error: {str(exc)}"})

    # Update upload record with results
    upload.rows_received = rows_received
    upload.rows_saved = rows_saved
    upload.validation_errors = errors
    upload.status = (
        TimetableUploadBatch.Status.PROCESSED
        if not errors
        else (
            TimetableUploadBatch.Status.PROCESSED
            if rows_saved > 0
            else TimetableUploadBatch.Status.FAILED
        )
    )
    upload.processed_at = timezone.now()
    upload.save(
        update_fields=[
            "rows_received",
            "rows_saved",
            "validation_errors",
            "status",
            "processed_at",
        ]
    )

    if progress_callback:
        progress_callback(
            rows_received,
            rows_saved,
            f"Complete: {rows_saved}/{rows_received} rows saved"
        )

    return upload


def _save_slot_batch(
    batch: list[TimetableSlot],
    upload: TimetableUploadBatch,
    errors: list[dict],
    row_num: int,
) -> int:
    """
    Save a batch of slots using bulk operations with deduplication.

    Returns:
        Number of slots successfully saved
    """
    if not batch:
        return 0

    saved_count = 0
    for slot in batch:
        slot.upload_batch = upload
        try:
            _, created = TimetableSlot.objects.update_or_create(
                term=slot.term,
                unit=slot.unit,
                program=slot.program,
                year_of_study=slot.year_of_study,
                day=slot.day,
                start_time=slot.start_time,
                defaults={
                    "end_time": slot.end_time,
                    "lecturer": slot.lecturer,
                    "room": slot.room,
                    "class_group": slot.class_group,
                    "upload_batch": upload,
                },
            )
            saved_count += 1
        except Exception as exc:
            errors.append({
                "row": row_num,
                "error": f"Database error: {str(exc)}"
            })

    return saved_count


def to_timetable_slot_dicts_from_batch(raw_slots):
    """Convert a batch of RawSlot objects to row dicts."""
    from apps.timetable.services.pdf_timetable_parser import normalise_unit_code
    
    out = []
    for s in raw_slots:
        out.append(
            {
                "cohort_label": s.cohort_label,
                "day": s.day,
                "start_time": f"{s.start_time}:00",
                "end_time": f"{s.end_time}:00",
                "unit_code": normalise_unit_code(s.unit_code_raw),
                "venue": f"{s.venue} {s.room}" if s.venue else None,
                "lecturer_name_text": "",
                "source_page": s.page,
            }
        )
    return out


# Backwards compatibility: delegate to streaming version
def process_upload(upload: TimetableUploadBatch) -> TimetableUploadBatch:
    """
    Legacy wrapper for process_upload_streaming.
    Automatically uses streaming for PDFs, traditional parsing for Excel/DOCX.
    """
    return process_upload_streaming(upload)

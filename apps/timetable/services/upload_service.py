"""
Orchestrates the full timetable upload pipeline:
  1. Parse PDF/Excel/DOCX
  2. Map each row to model instances
  3. Bulk-create TimetableSlot records with deduplication
  4. Write results to TimetableUpload audit record

IMPORTANT: This module now uses streaming/chunking for memory efficiency,
especially for large PDF files. Use process_upload() for automatic
handling of all file types with optimal memory usage.
"""
from __future__ import annotations

import os
import tempfile

from django.utils import timezone

from apps.timetable.models import AcademicTerm, TimetableSlot, TimetableUploadBatch
from apps.timetable.services.docx_timetable_parser import parse_docx
from apps.timetable.services.excel_parser import parse_excel
from apps.timetable.services.pdf_timetable_parser import parse_pdf, to_timetable_slot_dicts
from apps.timetable.services.mapper import (
    resolve_department, resolve_lecturer, resolve_program,
    resolve_room, resolve_time, resolve_unit,
)


def _get_or_create_term(academic_year: str, semester: int) -> AcademicTerm:
    term = AcademicTerm.objects.filter(
        academic_year=academic_year, semester=semester
    ).first()
    if not term:
        from datetime import date, timedelta
        today = date.today()
        term = AcademicTerm.objects.create(
            academic_year=academic_year,
            semester=semester,
            start_date=today,
            end_date=today + timedelta(days=120),
            is_current=False,
        )
    return term


def _parse_uploaded_file(upload: TimetableUploadBatch) -> list[dict]:
    ext = os.path.splitext(upload.source_file.name)[1].lower().lstrip(".")
    tmp_path = None

    if ext in ("xlsx", "xls", "csv"):
        return parse_excel(upload.source_file)
    
    elif ext == "pdf":
        try:
            # PDF parser expects a path, so write to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                for chunk in upload.source_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            parse_result = parse_pdf(tmp_path)
            return to_timetable_slot_dicts(parse_result)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass
    
    elif ext == "docx":
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                for chunk in upload.source_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            return parse_docx(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    else:
        raise ValueError(f"Unsupported file type: .{ext}")


def process_upload(upload: TimetableUploadBatch) -> TimetableUploadBatch:
    """
    Process timetable upload with automatic memory-efficient handling.
    
    For PDF files, uses streaming chunking to avoid loading entire file into memory.
    For Excel/DOCX, uses traditional parsing (can be optimized later).
    
    This is the main entry point for timetable upload processing.
    """
    # Import here to avoid circular imports
    from apps.timetable.services.upload_service_streaming import process_upload_streaming
    
    return process_upload_streaming(upload)


def process_upload_legacy(upload: TimetableUploadBatch) -> TimetableUploadBatch:
    """
    Legacy implementation that loads entire file into memory.
    Use process_upload() for new code; kept for backwards compatibility.
    """
    upload.status = TimetableUploadBatch.Status.VALIDATED
    upload.save(update_fields=["status"])

    errors = []
    slots_to_create = []

    try:
        rows = _parse_uploaded_file(upload)
    except ValueError as exc:
        upload.status = TimetableUploadBatch.Status.FAILED
        upload.validation_errors = [{"row": 0, "error": str(exc)}]
        upload.save(update_fields=["status", "validation_errors"])
        return upload

    upload.rows_received = len(rows)
    upload.save(update_fields=["rows_received"])

    for i, row in enumerate(rows, start=2):  # row 1 = header
        try:
            department = resolve_department(row)
            program = resolve_program(row, department)
            unit = resolve_unit(row, department)
            if not unit:
                raise ValueError("unit_code is missing or unresolvable")

            room = resolve_room(row)
            lecturer = resolve_lecturer(row, department)
            start_time, end_time = resolve_time(row)
            if not start_time or not end_time:
                raise ValueError("start_time and end_time are required")

            day = str(row.get("day") or "").upper()
            if day not in [c.value for c in TimetableSlot.WeekDay]:
                raise ValueError(f"Invalid day: {day!r}")

            academic_year = str(row.get("academic_year") or "2026/2027").strip()
            semester = int(row.get("semester") or 1)
            year_of_study = int(row.get("year_of_study") or 1)
            term = _get_or_create_term(academic_year, semester)

            slots_to_create.append(
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
                )
            )
        except Exception as exc:
            errors.append({"row": i, "error": str(exc)})

    # Bulk insert — ignore duplicates via update_or_create on conflicts
    saved = 0
    for slot in slots_to_create:
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
            },
        )
        saved += 1

    upload.rows_saved = saved
    upload.validation_errors = errors
    upload.processed_at = timezone.now()
    upload.status = (
        TimetableUploadBatch.Status.PROCESSED
        if not errors
        else (
            TimetableUploadBatch.Status.PROCESSED
            if saved
            else TimetableUploadBatch.Status.FAILED
        )
    )
    upload.save(update_fields=[
        "rows_saved", "validation_errors", "processed_at", "status"
    ])
    return upload

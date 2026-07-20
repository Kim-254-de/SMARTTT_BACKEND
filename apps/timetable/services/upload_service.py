"""
Orchestrates the full timetable upload pipeline:
  1. Parse Excel
  2. Map each row to model instances
  3. Bulk-create TimetableSlot records
  4. Write results to TimetableUpload audit record
"""
from __future__ import annotations

from django.utils import timezone

from apps.timetable.models import AcademicTerm, TimetableSlot, TimetableUpload
from apps.timetable.services.excel_parser import parse_excel
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


def process_upload(upload: TimetableUpload) -> TimetableUpload:
    upload.status = TimetableUpload.Status.PROCESSING
    upload.save(update_fields=["status"])

    errors = []
    slots_to_create = []

    try:
        rows = parse_excel(upload.uploaded_file)
    except ValueError as exc:
        upload.status = TimetableUpload.Status.FAILED
        upload.errors = [{"row": 0, "error": str(exc)}]
        upload.save(update_fields=["status", "errors"])
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
            if day not in [c.value for c in TimetableSlot.Day]:
                raise ValueError(f"Invalid day: {day!r}")

            academic_year = str(row.get("academic_year") or "2025/2026").strip()
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
    upload.rows_failed = len(errors)
    upload.errors = errors
    upload.processed_at = timezone.now()
    upload.status = (
        TimetableUpload.Status.DONE
        if not errors
        else (TimetableUpload.Status.PARTIAL if saved else TimetableUpload.Status.FAILED)
    )
    upload.save(update_fields=[
        "rows_saved", "rows_failed", "errors", "processed_at", "status"
    ])
    return upload

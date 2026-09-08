"""Formatting helpers for personalized timetable responses."""

from __future__ import annotations

from collections import OrderedDict
from datetime import time

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DAY_LABELS = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
    "SUN": "Sunday",
}


def format_time_value(value: time | None) -> str | None:
    if value is None:
        return None
    if value.minute == 0:
        return value.strftime("%I%p").lstrip("0")
    formatted = value.strftime("%I:%M%p")
    return formatted.lstrip("0")


def serialize_unit(unit) -> dict:
    return {
        "id": str(unit.id),
        "code": unit.code,
        "title": unit.name,
        "credit_hours": unit.credit_hours,
        "department_id": str(unit.department_id) if unit.department_id else None,
    }


def serialize_session(session) -> dict:
    # 1. First check registered lecturer account
    lecturer_name = None
    if session.lecturer and hasattr(session.lecturer, "user") and session.lecturer.user:
        lecturer_name = session.lecturer.user.get_full_name().strip()

    # 2. Fall back to text field on session or related slot
    if not lecturer_name:
        lecturer_name = getattr(session, "lecturer_name_text", "") or ""

    if not lecturer_name and hasattr(session, "slot"):
        lecturer_name = getattr(session.slot, "lecturer_name_text", "") or ""

    start_time_val = getattr(session.time_slot, "start_time", None) if hasattr(session, "time_slot") else getattr(session, "start_time", None)
    end_time_val = getattr(session.time_slot, "end_time", None) if hasattr(session, "time_slot") else getattr(session, "end_time", None)
    slot_name_val = getattr(session.time_slot, "slot_name", "") if hasattr(session, "time_slot") else ""

    return {
        "id": str(session.id),
        "unit": serialize_unit(session.unit),
        "program_id": str(session.program_id) if session.program_id else None,
        "department_id": str(session.department_id) if session.department_id else None,
        "study_year": getattr(session, "study_year", None),
        "semester": getattr(session, "semester", None),
        "day_of_week": session.day_of_week,
        "day_label": DAY_LABELS.get(session.day_of_week, session.day_of_week),
        "start_time": format_time_value(start_time_val),
        "end_time": format_time_value(end_time_val),
        "time_slot": slot_name_val,
        "room": {
            "id": str(session.room_id) if session.room_id else None,
            "code": getattr(session.room, "code", None),
            "name": getattr(session.room, "name", None),
        },
        "lecturer": {
            "id": str(session.lecturer_id) if session.lecturer_id else None,
            "name": lecturer_name if lecturer_name else None,
        },
        "session_type": getattr(session, "session_type", None),
        "delivery_mode": getattr(session, "delivery_mode", None),
        "status": getattr(session, "status", None),
    }


def build_empty_timetable() -> dict:
    return OrderedDict((DAY_LABELS[day], []) for day in DAY_ORDER)


def group_sessions_by_day(sessions) -> dict:
    grouped = build_empty_timetable()
    for session in sessions:
        grouped.setdefault(
            DAY_LABELS.get(session.day_of_week, session.day_of_week), []
        ).append(serialize_session(session))
    return grouped

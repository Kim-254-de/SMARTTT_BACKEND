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
	return {
		"id": str(session.id),
		"unit": serialize_unit(session.unit),
		"program_id": str(session.program_id) if session.program_id else None,
		"department_id": str(session.department_id) if session.department_id else None,
		"study_year": session.study_year,
		"semester": session.semester,
		"day_of_week": session.day_of_week,
		"day_label": DAY_LABELS.get(session.day_of_week, session.day_of_week),
		"start_time": format_time_value(session.time_slot.start_time),
		"end_time": format_time_value(session.time_slot.end_time),
		"time_slot": session.time_slot.slot_name,
		"room": {
			"id": str(session.room_id) if session.room_id else None,
			"code": getattr(session.room, "code", None),
			"name": getattr(session.room, "name", None),
		},
		"lecturer": {
			"id": str(session.lecturer_id) if session.lecturer_id else None,
			"name": session.lecturer.user.get_full_name() if session.lecturer and session.lecturer.user else None,
		},
		"session_type": session.session_type,
		"delivery_mode": session.delivery_mode,
		"status": session.status,
	}


def build_empty_timetable() -> dict:
	return OrderedDict((DAY_LABELS[day], []) for day in DAY_ORDER)


def group_sessions_by_day(sessions) -> dict:
	grouped = build_empty_timetable()
	for session in sessions:
		grouped.setdefault(DAY_LABELS.get(session.day_of_week, session.day_of_week), []).append(
			serialize_session(session)
		)
	return grouped

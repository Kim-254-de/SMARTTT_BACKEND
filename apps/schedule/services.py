"""
Personalised timetable service.

Algorithm:
  1. Get the student's registered units for the current term (StudentUnit table)
  2. Get the current academic term
  3. Query TimetableSlot WHERE unit IN student_units AND term = current_term
  4. Group slots by day, sort by start_time
  5. Detect and flag time conflicts
  6. Return structured payload
"""
from __future__ import annotations

from collections import defaultdict

from apps.courses.models import StudentUnit
from apps.timetable.models import AcademicTerm, TimetableSlot

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _has_overlap(slot_a: TimetableSlot, slot_b: TimetableSlot) -> bool:
    return slot_a.start_time < slot_b.end_time and slot_a.end_time > slot_b.start_time


def generate_for_user(user) -> dict:
    """
    Returns:
    {
        "term": "2025/2026 Sem 1",
        "units": [...],
        "timetable": {"MON": [...], "TUE": [...], ...},
        "conflicts": [...],
        "summary": {"unit_count": 4, "session_count": 12, "has_conflicts": false}
    }
    """
    # ── 1. Current term ────────────────────────────────────────────────────────
    term = AcademicTerm.objects.filter(is_current=True).first()
    if not term:
        return {
            "term": None,
            "units": [],
            "timetable": {day: [] for day in DAY_ORDER},
            "conflicts": [],
            "summary": {"unit_count": 0, "session_count": 0, "has_conflicts": False,
                        "message": "No current academic term configured."},
        }

    # ── 2. Student's registered units this term ────────────────────────────────
    student_units = (
        StudentUnit.objects.select_related("unit", "unit__department")
        .filter(user=user, term=term)
    )
    unit_ids = [su.unit_id for su in student_units]
    unit_data = [
        {"id": str(su.unit.id), "code": su.unit.code, "name": su.unit.name}
        for su in student_units
    ]

    if not unit_ids:
        return {
            "term": str(term),
            "units": [],
            "timetable": {day: [] for day in DAY_ORDER},
            "conflicts": [],
            "summary": {"unit_count": 0, "session_count": 0, "has_conflicts": False,
                        "message": "No registered units found. Use My Courses to sync your units."},
        }

    # ── 3. Fetch matching timetable slots ──────────────────────────────────────
    slots = list(
        TimetableSlot.objects.select_related(
            "unit", "program", "lecturer__user", "room", "term"
        ).filter(term=term, unit_id__in=unit_ids)
        .order_by("day", "start_time")
    )

    # ── 4. Group by day ────────────────────────────────────────────────────────
    grouped: dict[str, list] = {day: [] for day in DAY_ORDER}
    for slot in slots:
        grouped.setdefault(slot.day, []).append(_serialise_slot(slot))

    # Sort each day by start_time
    for day in grouped:
        grouped[day].sort(key=lambda s: s["start_time"])

    # ── 5. Detect conflicts (two slots on same day overlapping in time) ────────
    conflicts = []
    for day, day_slots in grouped.items():
        raw_day_slots = [s for s in slots if s.day == day]
        for i, a in enumerate(raw_day_slots):
            for b in raw_day_slots[i + 1:]:
                if _has_overlap(a, b):
                    conflicts.append({
                        "day": day,
                        "unit_a": a.unit.code,
                        "unit_b": b.unit.code,
                        "time": f"{a.start_time:%H:%M}–{a.end_time:%H:%M}",
                    })

    return {
        "term": str(term),
        "units": unit_data,
        "timetable": grouped,
        "conflicts": conflicts,
        "summary": {
            "unit_count": len(unit_ids),
            "session_count": len(slots),
            "has_conflicts": bool(conflicts),
        },
    }


def _serialise_slot(slot: TimetableSlot) -> dict:
    return {
        "id": str(slot.id),
        "unit_code": slot.unit.code,
        "unit_name": slot.unit.name,
        "day": slot.day,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.code if slot.room else None,
        "lecturer": slot.lecturer.user.get_full_name() if slot.lecturer else None,
        "program": slot.program.name if slot.program else None,
        "year_of_study": slot.year_of_study,
    }

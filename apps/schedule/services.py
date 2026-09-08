"""
Personalised timetable service.

Algorithm:
  1. Get the student's registered units for the current term (StudentUnit table)
  2. Get the current academic term
  3. Query TimetableSlot WHERE unit IN student_units AND term = current_term
  4. Deduplicate identical slots caused by multiple timetable uploads
  5. Group slots by day, sort by start_time
  6. Detect and flag legitimate time conflicts
  7. Return structured payload
"""
from __future__ import annotations

from apps.courses.models import StudentUnit
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.utils.day_order import day_of_week_sort_case

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _has_overlap(slot_a: TimetableSlot, slot_b: TimetableSlot) -> bool:
    return slot_a.start_time < slot_b.end_time and slot_a.end_time > slot_b.start_time


def generate_for_user(user) -> dict:
    """
    Returns:
    {
        "term": "2026/2027 S1",
        "units": [...],
        "timetable": {"MON": [...], "TUE": [...], ...},
        "conflicts": [...],
        "summary": {"unit_count": 5, "session_count": 5, "has_conflicts": false}
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
            "summary": {
                "unit_count": 0,
                "session_count": 0,
                "has_conflicts": False,
                "message": "No current academic term configured.",
            },
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
            "summary": {
                "unit_count": 0,
                "session_count": 0,
                "has_conflicts": False,
                "message": "No registered units found. Use Sync to update your schedule.",
            },
        }

    # ── 3. Fetch matching timetable slots ──────────────────────────────────────
    raw_slots = list(
        TimetableSlot.objects.select_related(
            "unit", "program", "lecturer__user", "room", "term"
        )
        .filter(term=term, unit_id__in=unit_ids)
        .annotate(_day_sort=day_of_week_sort_case())
        .order_by("_day_sort", "start_time")
    )

    # ── 3b. DEDUPLICATION: Purge duplicate slots from repeated file uploads ─────
    seen_signatures = set()
    slots: list[TimetableSlot] = []
    for slot in raw_slots:
        # Signature uniquely identifies a distinct scheduled session
        signature = (
            slot.unit_id,
            slot.day_of_week.upper() if slot.day_of_week else "",
            slot.start_time,
            slot.end_time,
            slot.room_id,
        )
        if signature not in seen_signatures:
            seen_signatures.add(signature)
            slots.append(slot)

    # ── 4. Group by day ────────────────────────────────────────────────────────
    grouped: dict[str, list] = {day: [] for day in DAY_ORDER}
    for slot in slots:
        day_key = slot.day_of_week.upper() if slot.day_of_week else "MON"
        grouped.setdefault(day_key, []).append(_serialise_slot(slot))

    # Sort each day by start_time
    for day in grouped:
        grouped[day].sort(key=lambda s: s["start_time"])

    # ── 5. Detect genuine conflicts between DIFFERENT units ────────────────────
    conflicts = []
    for day, _ in grouped.items():
        raw_day_slots = [s for s in slots if s.day_of_week and s.day_of_week.upper() == day]
        for i, a in enumerate(raw_day_slots):
            for b in raw_day_slots[i + 1:]:
                # Only flag conflicts between different course units
                if a.unit_id != b.unit_id and _has_overlap(a, b):
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
    unit_code = slot.unit.code if slot.unit else ""
    # Use real unit title if available, otherwise fallback to slot.unit.name
    unit_title = slot.unit.name if slot.unit and slot.unit.name != unit_code else unit_code

    # 1. Registered lecturer FK
    lecturer_name = None
    if slot.lecturer and hasattr(slot.lecturer, "user") and slot.lecturer.user:
        lecturer_name = slot.lecturer.user.get_full_name().strip()

    # 2. Text name from Word allocation
    if not lecturer_name:
        candidate = getattr(slot, "lecturer_name_text", "") or ""
        # GUARD: Ensure candidate is not just the course title or course code!
        if candidate and candidate.strip().lower() != unit_title.strip().lower() and candidate.strip().lower() != unit_code.strip().lower():
            lecturer_name = candidate.strip()

    return {
        "id": str(slot.id),
        "unit_code": unit_code,
        "unit_name": unit_title,
        "day": slot.day_of_week.upper() if slot.day_of_week else "MON",
        "start_time": slot.start_time.strftime("%H:%M") if slot.start_time else "",
        "end_time": slot.end_time.strftime("%H:%M") if slot.end_time else "",
        "room": slot.room.code if slot.room else "TBA",
        "lecturer": lecturer_name or "Lecturer TBA",
        "program": slot.program.name if slot.program else None,
        "year_of_study": slot.year_of_study,
    }

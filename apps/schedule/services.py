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

from django.db.models import Q

from apps.courses.models import StudentUnit
from apps.programs.models import Program
from apps.programs.utils import canonical_program_key
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.utils.day_order import day_of_week_sort_case

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _has_overlap(slot_a: TimetableSlot, slot_b: TimetableSlot) -> bool:
    return slot_a.start_time < slot_b.end_time and slot_a.end_time > slot_b.start_time


def _program_ids_for_student(student) -> list:
    """
    A program can exist as several duplicate Program rows - different
    timetable uploads (e.g. the master timetable vs. a later allocation
    supplement) can parse the same program header with slightly different
    text and each create their own row (see apps.programs.utils for why).
    student.program only ever points at one of those rows, but that
    program's TimetableSlot rows can be split across all of its
    duplicates - e.g. a shared unit's ungrouped "MAIN" slot landing under
    one duplicate while its group-split slots landed under another. Match
    every row that canonically resolves to the same program name, not
    just the single one saved on the profile.
    """
    program = getattr(student, "program", None)
    if not program:
        return []
    key = canonical_program_key(program.name)
    return [
        p.id for p in Program.objects.only("id", "name")
        if canonical_program_key(p.name) == key
    ]


def get_matching_slots(user, term, unit_ids) -> list[TimetableSlot]:
    """
    The student's own TimetableSlot rows for `unit_ids` this term - shared by
    generate_for_user (JSON schedule) and the .ics calendar feed, so both
    narrow a shared unit down to the student's own class (see the filtering
    rationale below) and dedupe identical rows from repeated uploads the
    same way.
    """
    # A shared unit (e.g. a foundation course like EDCI or EPSC) can be taught
    # to several different combinations/streams in parallel, each as its own
    # TimetableSlot row. Filtering by unit alone would return every one of
    # those - not just the student's own class. Narrow by the student's
    # program (their exact combination, e.g. "BED.MATH/CHEM" - resolved via
    # the preferences screen, see ProfileView.patch's program_id handling,
    # and widened to cover duplicate Program rows - see
    # _program_ids_for_student) and, when set, their stream (the numbered
    # sub-class within that program+year, e.g. the "1" in "...Y3S1(1)" - see
    # TimetableSlot.stream). Slots with a blank stream aren't split into
    # multiple classes for that unit, so they always match regardless of the
    # student's stream.
    student = getattr(user, "student_profile", None)
    program_ids = _program_ids_for_student(student)
    stream = (getattr(student, "timetable_group", None) or "").strip()

    slot_filter = Q(term=term, unit_id__in=unit_ids)
    if program_ids:
        slot_filter &= Q(program_id__in=program_ids)
    if stream:
        slot_filter &= (Q(stream=stream) | Q(stream=""))

    raw_slots = list(
        TimetableSlot.objects.select_related(
            "unit", "program", "lecturer__user", "room", "term"
        )
        .filter(slot_filter)
        .annotate(_day_sort=day_of_week_sort_case())
        .order_by("_day_sort", "start_time")
    )

    # DEDUPLICATION: purge duplicate slots from repeated file uploads.
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
    return slots


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
    slots = get_matching_slots(user, term, unit_ids)

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

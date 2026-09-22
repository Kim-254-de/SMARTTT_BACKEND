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
from apps.timetable.services.allocation_matcher import display_lecturer
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


def _base_unit_slot_queryset(student, term, unit_id):
    """
    TimetableSlot rows for a single unit, narrowed to the student's program
    (see _program_ids_for_student) and stream, but *not* yet narrowed by
    class_group - the shared starting point for both available_groups_for_unit
    (which needs to see every group to list them) and get_matching_slots
    (which narrows further once a choice is known).
    """
    program_ids = _program_ids_for_student(student)
    stream = (getattr(student, "timetable_group", None) or "").strip()

    qs = TimetableSlot.objects.filter(term=term, unit_id=unit_id)
    if program_ids:
        qs = qs.filter(program_id__in=program_ids)
    if stream:
        qs = qs.filter(Q(stream=stream) | Q(stream=""))
    return qs


def available_groups_for_unit(user, term, unit_id) -> list[str]:
    """
    Distinct elective/practical group letters (e.g. "GR B") this unit is
    split into for the student's own program+stream, excluding "MAIN".
    Empty means the unit isn't split - there's nothing to pick between, so
    every one of its sessions is the student's own regardless of group.
    """
    student = getattr(user, "student_profile", None)
    if not student:
        return []
    raw = _base_unit_slot_queryset(student, term, unit_id).values_list("class_group", flat=True)
    return sorted({
        g.strip() for g in raw
        if g and g.strip() and g.strip().upper() != "MAIN"
    })


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

    # Different unit pools within the same stream can be split into groups
    # with unrelated lettering at the same time (e.g. EDCI/EPSC's "GR J" vs
    # MATH's "GR C" vs CHEM's "GR B", all within "...Y3S1(1)") - there's no
    # single stream-wide group letter that works for every unit. So the
    # student's chosen group is tracked per-unit on StudentUnit.class_group
    # (see available_groups_for_unit / apps.courses.views.SetUnitGroupView),
    # not as a second flat field alongside `stream`. A unit with no choice
    # made yet (or that isn't split at all) keeps showing every group's
    # sessions, same as before this existed.
    chosen_groups = dict(
        StudentUnit.objects.filter(user=user, term=term, unit_id__in=unit_ids)
        .exclude(class_group="")
        .values_list("unit_id", "class_group")
    )

    unit_filter = Q()
    for uid in unit_ids:
        chosen = chosen_groups.get(uid)
        if chosen:
            unit_filter |= Q(unit_id=uid, class_group__iexact=chosen) | Q(unit_id=uid, class_group__iexact="MAIN")
        else:
            unit_filter |= Q(unit_id=uid)

    slot_filter = Q(term=term) & unit_filter
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
        # Signature uniquely identifies a distinct scheduled session. Uses
        # the room's CODE text (formatting-insensitive, like
        # canonical_program_key) rather than its FK id: a room can end up as
        # several duplicate Room rows across separate uploads the same way
        # Program does (e.g. "TC5" vs "TC 5" for the same physical venue -
        # see _program_ids_for_student), so two uploads' rows for what is
        # really the same class at the same time/room would otherwise carry
        # different room_id values - and merely stripping outer whitespace
        # wouldn't catch a space *inside* the code - and slip past this
        # dedup as if they were two distinct sessions.
        room_key = canonical_program_key(slot.room.code) if slot.room_id else ""
        signature = (
            slot.unit_id,
            slot.day_of_week.upper() if slot.day_of_week else "",
            slot.start_time,
            slot.end_time,
            room_key,
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
        {
            "id": str(su.unit.id),
            "code": su.unit.code,
            "name": su.unit.name,
            "selected_group": su.class_group or None,
            # Non-empty only when this unit is actually split into more than
            # one elective/practical group for the student's program+stream
            # - the app should prompt to pick one of these (via
            # PATCH /courses/my-courses/{id}/group/) when selected_group is
            # still null, rather than silently showing every group's
            # sessions - see get_matching_slots.
            "available_groups": available_groups_for_unit(user, term, su.unit_id),
        }
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

    # Registered lecturer account and/or the name from the department allocation
    account_name = ""
    if slot.lecturer and hasattr(slot.lecturer, "user") and slot.lecturer.user:
        account_name = slot.lecturer.user.get_full_name().strip()
    candidate = (getattr(slot, "lecturer_name_text", "") or "").strip()
    # GUARD: Ensure candidate is not just the course title or course code!
    if candidate.lower() in {unit_title.strip().lower(), unit_code.strip().lower()}:
        candidate = ""
    lecturer_name = display_lecturer(account_name, candidate) or None

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

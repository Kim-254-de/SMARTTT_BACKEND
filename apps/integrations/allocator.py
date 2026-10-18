"""
What the Timetable Allocator (the departments' lecturer allocation system)
reads from and writes to the published timetable.

The Allocator assigns a lecturer to each *section*: one unit taught to one
teaching group ("COSC 103 GR A", or plain "COSC 103" when the unit isn't
split). A section is usually several TimetableSlot rows - one per class row
(programme + year + stream) it serves, and one per weekly meeting - and they
all carry the same lecturer. A section is identified by its key,
"<unit id>-<group key>", e.g. "412-GRA" or "412-MAIN"; it is stable across
republished versions as long as the unit and group stay the same.

The department that *owns the unit* allocates its lecturer, including when it
teaches another department's students ("servicing").

Setting a lecturer is checked here under a lock (set_section_lecturer), not
only in the Allocator: two departments can try to give the same part-time
lecturer two classes at the same hour, and only the check made while holding
the lecturer's row lock decides.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.integrations.services import group_key, group_label, name_query, section_code
from apps.lecturers.models import Lecturer
from apps.timetable.models import AcademicTerm, TimetableSlot

MAIN_KEY = "MAIN"
_KEY_RE = re.compile(r"^(?P<unit>\d+)-(?P<group>[A-Z0-9]+)$")


def section_key(unit_id, class_group: str | None) -> str:
    return f"{unit_id}-{group_key(class_group) or MAIN_KEY}"


def parse_section_key(key: str) -> tuple[int, str] | None:
    """(unit id, group key; "" for MAIN), or None when the key is malformed."""
    match = _KEY_RE.match((key or "").strip().upper())
    if not match:
        return None
    group = match.group("group")
    return int(match.group("unit")), "" if group == MAIN_KEY else group


def resolve_term(term_id: str | None) -> AcademicTerm | None:
    """The requested term, else the current one. None when neither exists."""
    if term_id:
        try:
            return AcademicTerm.objects.filter(pk=term_id).first()
        except (ValueError, TypeError, ValidationError):
            return None
    return AcademicTerm.objects.filter(is_current=True).first()


def term_dict(term: AcademicTerm) -> dict:
    return {
        "id": str(term.id),
        "academic_year": term.academic_year,
        "semester": term.semester,
        "start_date": term.start_date.isoformat(),
        "end_date": term.end_date.isoformat(),
        "is_current": term.is_current,
    }


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _day(value: str) -> str:
    return (value or "").strip().upper()[:3]


def _minutes(start: time, end: time) -> int:
    return int((datetime.combine(datetime.min, end) - datetime.combine(datetime.min, start)).total_seconds() // 60)


def lecturer_dict(lecturer: Lecturer) -> dict:
    user = lecturer.user
    return {
        "id": str(lecturer.id),
        "staff_number": (user.university_id or "").strip().upper() or None,
        "full_name": user.get_full_name().strip() or user.username,
        "title": (lecturer.rank or "").strip() or None,
        "employment_type": lecturer.employment_type,
        "max_weekly_teaching_hours": lecturer.max_weekly_teaching_hours,
        "department": {
            "id": lecturer.department_id,
            "code": lecturer.department.code,
            "name": lecturer.department.name,
        },
        "is_active": bool(user.is_active),
    }


# ---------------------------------------------------------------------------
# Reading sections
# ---------------------------------------------------------------------------


def _section_slots(term: AcademicTerm):
    return (
        TimetableSlot.objects.filter(term=term, unit__isnull=False)
        .select_related("unit__department", "room", "program", "lecturer__user", "lecturer__department")
        .order_by("unit__code", "class_group", "day_of_week", "start_time")
    )


def build_sections(slots) -> list[dict]:
    """Groups slots into sections, each with its class rows, meetings and lecturer."""
    sections: dict[str, dict] = {}
    for slot in slots:
        unit = slot.unit
        key = section_key(unit.id, slot.class_group)
        entry = sections.get(key)
        if entry is None:
            entry = sections[key] = {
                "key": key,
                "code": section_code(unit.code, slot.class_group),
                "unit": {
                    "id": unit.id,
                    "code": unit.code,
                    "name": unit.name,
                    "credit_hours": float(unit.credit_hours),
                    "department_id": unit.department_id,
                },
                "group": group_label(slot.class_group) or None,
                "class_rows": [],
                "meetings": [],
                "lecturer": None,
                "lecturer_name_text": "",
                "session_keys": [],
                "_rows": set(),
                "_meetings": set(),
                "_lecturers": {},
            }
        row = (slot.program_id, slot.year_of_study, slot.stream or "")
        if row not in entry["_rows"]:
            entry["_rows"].add(row)
            entry["class_rows"].append({
                "program_id": slot.program_id,
                "program_code": slot.program.code if slot.program else None,
                "program_name": slot.program.name if slot.program else None,
                "year_of_study": slot.year_of_study,
                "study_semester": slot.study_semester,
                "stream": slot.stream or "",
            })
        meeting = (_day(slot.day_of_week), slot.start_time, slot.end_time, slot.room_id)
        if meeting not in entry["_meetings"]:
            entry["_meetings"].add(meeting)
            entry["meetings"].append({
                "day_of_week": meeting[0],
                "start_time": _hhmm(slot.start_time),
                "end_time": _hhmm(slot.end_time),
                "room": {"id": str(slot.room_id), "code": slot.room.code, "capacity": slot.room.capacity},
                "session_key": slot.session_key or None,
            })
        if slot.session_key and slot.session_key not in entry["session_keys"]:
            entry["session_keys"].append(slot.session_key)
        if slot.lecturer_id:
            entry["_lecturers"][slot.lecturer_id] = slot.lecturer
        elif slot.lecturer_name_text and not entry["lecturer_name_text"]:
            entry["lecturer_name_text"] = slot.lecturer_name_text

    day_order = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
    result = []
    for entry in sections.values():
        lecturers = list(entry.pop("_lecturers").values())
        entry.pop("_rows")
        entry.pop("_meetings")
        # Every slot of a section gets the same lecturer when set through the
        # Allocator; slots set by older document uploads may disagree, which is
        # reported so the department can settle it.
        entry["lecturer"] = lecturer_dict(lecturers[0]) if len(lecturers) == 1 else None
        entry["lecturer_conflict"] = len(lecturers) > 1
        minutes = sum(_minutes(_parse_hhmm(m["start_time"]), _parse_hhmm(m["end_time"])) for m in entry["meetings"])
        entry["weekly_hours"] = round(minutes / 60, 2)
        entry["meetings"].sort(key=lambda m: (day_order.get(m["day_of_week"], 9), m["start_time"]))
        result.append(entry)
    return sorted(result, key=lambda e: e["code"])


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def department_sections(term: AcademicTerm, department_id: int) -> list[dict]:
    """The published sections whose unit this department owns, servicing included."""
    sections = build_sections(_section_slots(term).filter(unit__department_id=department_id))
    _attach_registrations(term, sections)
    return sections


def find_section(term: AcademicTerm, key: str) -> dict | None:
    parsed = parse_section_key(key)
    if parsed is None:
        return None
    unit_id, gkey = parsed
    slots = [s for s in _section_slots(term).filter(unit_id=unit_id) if group_key(s.class_group) == gkey]
    if not slots:
        return None
    sections = build_sections(slots)
    _attach_registrations(term, sections)
    return sections[0]


def _attach_registrations(term: AcademicTerm, sections: list[dict]) -> None:
    """registered_students per section: the unit for MAIN, else those who picked the group."""
    from apps.courses.models import StudentUnit

    unit_ids = {s["unit"]["id"] for s in sections}
    counts: dict[tuple[int, str], set] = {}
    for unit_id, user_id, class_group in StudentUnit.objects.filter(term=term, unit_id__in=unit_ids).values_list(
        "unit_id", "user_id", "class_group"
    ):
        counts.setdefault((unit_id, ""), set()).add(user_id)
        gkey = group_key(class_group)
        if gkey:
            counts.setdefault((unit_id, gkey), set()).add(user_id)
    for section in sections:
        parsed = parse_section_key(section["key"])
        section["registered_students"] = len(counts.get(parsed, set())) if parsed else 0


# ---------------------------------------------------------------------------
# A lecturer's week
# ---------------------------------------------------------------------------


def _owned_by(lecturer: Lecturer) -> Q:
    """
    A slot is the lecturer's when it is linked to their account, or - with no
    account linked - when the allocation document's name is theirs. The same
    rule the attendance roster uses (services.get_lecturer_units).
    """
    owner = Q(lecturer=lecturer)
    by_name = name_query(lecturer.user.get_full_name())
    if by_name is not None:
        owner |= Q(lecturer__isnull=True) & by_name
    return owner


def lecturer_meetings(term: AcademicTerm, lecturer: Lecturer, exclude_key: str | None = None) -> list[dict]:
    """Everything the lecturer teaches this term, across all departments, one entry per meeting."""
    slots = (
        TimetableSlot.objects.filter(Q(term=term) & Q(unit__isnull=False) & _owned_by(lecturer))
        .select_related("unit", "room")
        .order_by("day_of_week", "start_time")
    )
    seen: set[tuple] = set()
    meetings = []
    for slot in slots:
        key = section_key(slot.unit_id, slot.class_group)
        if key == exclude_key:
            continue
        signature = (key, _day(slot.day_of_week), slot.start_time, slot.end_time)
        if signature in seen:
            continue
        seen.add(signature)
        meetings.append({
            "section_key": key,
            "code": section_code(slot.unit.code, slot.class_group),
            "unit_department_id": slot.unit.department_id,
            "day_of_week": signature[1],
            "start_time": _hhmm(slot.start_time),
            "end_time": _hhmm(slot.end_time),
            "room": slot.room.code if slot.room_id else None,
            "linked": slot.lecturer_id == lecturer.id,
        })
    return meetings


def weekly_hours(meetings: list[dict]) -> float:
    """Teaching hours a week: each distinct (day, start, end) counted once."""
    distinct = {(m["day_of_week"], m["start_time"], m["end_time"]) for m in meetings}
    return round(sum(_minutes(_parse_hhmm(s), _parse_hhmm(e)) for _d, s, e in distinct) / 60, 2)


def overlaps(a: dict, b: dict) -> bool:
    return a["day_of_week"] == b["day_of_week"] and a["start_time"] < b["end_time"] and b["start_time"] < a["end_time"]


def clashes(section_meetings: list[dict], busy: list[dict]) -> list[dict]:
    """Each (meeting of the section, meeting it collides with) pair."""
    found = []
    for mine in section_meetings:
        for other in busy:
            if overlaps(mine, other):
                found.append({
                    "day_of_week": mine["day_of_week"],
                    "start_time": mine["start_time"],
                    "end_time": mine["end_time"],
                    "clashes_with": other["code"],
                    "clashes_with_key": other["section_key"],
                    "clashing_start_time": other["start_time"],
                    "clashing_end_time": other["end_time"],
                })
    return found


def department_lecturers(term: AcademicTerm | None, department_id: int | None) -> list[dict]:
    """
    Lecturers (of one department, or all), each with their week so far when a
    term is given, so the Allocator can work out who is free at a slot in one
    call instead of one per lecturer.
    """
    lecturers = Lecturer.objects.select_related("user", "department").filter(user__is_active=True)
    if department_id is not None:
        lecturers = lecturers.filter(department_id=department_id)
    result = []
    for lecturer in lecturers:
        entry = lecturer_dict(lecturer)
        if term is not None:
            meetings = lecturer_meetings(term, lecturer)
            entry["meetings"] = meetings
            entry["weekly_hours"] = weekly_hours(meetings)
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Setting a section's lecturer
# ---------------------------------------------------------------------------


class AllocationRefused(Exception):
    """The lecturer can't take this section. `code` says why, `details` lists the evidence."""

    def __init__(self, code: str, message: str, details: dict | None = None, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status


@dataclass
class AllocationResult:
    section: dict
    previous_lecturer_ids: list[str]
    changed: bool


def set_section_lecturer(
    term: AcademicTerm,
    key: str,
    lecturer_id: str | None,
    expected_lecturer_id: str | None | object = ...,
) -> AllocationResult:
    """
    Sets (or with lecturer_id None, clears) the lecturer on every slot of the
    section, in one transaction.

    Refused (AllocationRefused) when:
    - the section doesn't exist in the term (404);
    - the lecturer doesn't exist or is inactive (400);
    - `expected_lecturer_id` is given and is no longer the section's lecturer,
      i.e. someone else changed it since the caller looked (409 `stale`);
    - the lecturer teaches something else at one of the section's hours
      (409 `lecturer_clash`, H11);
    - it would take them past max_weekly_teaching_hours (409 `max_hours`, H12).

    The lecturer's row is locked (SELECT ... FOR UPDATE) for the check and
    the write, so two allocations of the same lecturer run one after the
    other and the second sees the first.
    """
    parsed = parse_section_key(key)
    if parsed is None:
        raise AllocationRefused("not_found", "No such section in this term.", status=404)
    unit_id, gkey = parsed

    with transaction.atomic():
        lecturer = None
        if lecturer_id is not None:
            try:
                lecturer = (
                    Lecturer.objects.select_for_update()
                    .select_related("user", "department")
                    .filter(pk=lecturer_id, user__is_active=True)
                    .first()
                )
            except (ValueError, TypeError, ValidationError):
                lecturer = None
            if lecturer is None:
                raise AllocationRefused("unknown_lecturer", "No active lecturer with this id.", status=400)

        slots = [
            slot
            for slot in TimetableSlot.objects.select_for_update()
            .filter(term=term, unit_id=unit_id)
            .order_by("id")
            if group_key(slot.class_group) == gkey
        ]
        if not slots:
            raise AllocationRefused("not_found", "No such section in this term.", status=404)

        current = {str(s.lecturer_id) for s in slots if s.lecturer_id}
        if expected_lecturer_id is not ...:
            expected = {str(expected_lecturer_id)} if expected_lecturer_id else set()
            if current != expected:
                raise AllocationRefused(
                    "stale",
                    "This class's lecturer was changed by someone else. Reload and try again.",
                    {"current_lecturer_ids": sorted(current)},
                )

        if lecturer is not None:
            mine = []
            seen = set()
            for slot in slots:
                signature = (_day(slot.day_of_week), slot.start_time, slot.end_time)
                if signature in seen:
                    continue
                seen.add(signature)
                mine.append({
                    "day_of_week": signature[0],
                    "start_time": _hhmm(slot.start_time),
                    "end_time": _hhmm(slot.end_time),
                })
            busy = lecturer_meetings(term, lecturer, exclude_key=key)
            found = clashes(mine, busy)
            if found:
                raise AllocationRefused(
                    "lecturer_clash",
                    f"{lecturer.user.get_full_name()} already teaches at this time.",
                    {"clashes": found},
                )
            total = weekly_hours(busy + [{**m, "section_key": key, "code": ""} for m in mine])
            if total > lecturer.max_weekly_teaching_hours:
                raise AllocationRefused(
                    "max_hours",
                    f"{lecturer.user.get_full_name()} would teach {total:g} hours a week; "
                    f"the limit is {lecturer.max_weekly_teaching_hours}.",
                    {"weekly_hours": total, "max_weekly_teaching_hours": lecturer.max_weekly_teaching_hours},
                )

        new_id = str(lecturer.id) if lecturer else None
        changed = current != ({new_id} if new_id else set()) or any(
            (s.lecturer_name_text or "") != (lecturer.user.get_full_name().strip() if lecturer else "")
            for s in slots
        )
        if changed:
            name = lecturer.user.get_full_name().strip() if lecturer else ""
            for slot in slots:
                slot.lecturer = lecturer
                slot.lecturer_name_text = name
                # Set by the department in the Allocator, not by a document row.
                slot.allocation_document = None
            TimetableSlot.objects.bulk_update(slots, ["lecturer", "lecturer_name_text", "allocation_document"])

    section = find_section(term, key)
    return AllocationResult(section=section, previous_lecturer_ids=sorted(current), changed=changed)

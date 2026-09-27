"""
What the Smart Attendance system needs from the timetable: the classes a
lecturer is timetabled to teach this term, how many students are registered
for each, and who they are (registration number and name) for its
attendance roster.

A class is a unit plus a teaching group. Big common units (COSC 103, EDFO
111 ...) are split into groups - "GR A", "GR B", "GR P" - each allocated to
its own lecturer (see timetable.services.allocation_matcher). Each group is
reported as its own section ("COSC 103 GR A") with only that group's
students: a StudentUnit whose class_group is that group. A unit that isn't
split (class_group MAIN) is one section with everyone registered for it.

A student who hasn't picked their group for a split unit yet (blank
StudentUnit.class_group) can't be placed in any group, so is on no group's
roster; each group section reports how many such students the unit has, so
the lecturer can nudge them to pick one in SMARTTT.

Mirrors the rules of accounts.views.auth_views.LecturerProfileView (the
lecturer dashboard) so both systems agree on "this lecturer's units":

- A slot is the lecturer's when its Lecturer account is theirs, OR when its
  `lecturer_name_text` (from the department allocation document) matches their
  name. Slots are only linked to an account once the lecturer opens their
  SMARTTT dashboard, so without the name match a lecturer who has never
  signed in to SMARTTT would appear to teach nothing.
- "Registered students" is the number of StudentUnit rows for the section
  (the unit, narrowed to the group) in the current term.

Unlike the dashboard, this is strictly read-only: it never claims a slot for
the lecturer's account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db.models import Q

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.timetable.models import AcademicTerm, TimetableSlot

# 0=Sunday..6=Saturday, the convention the attendance backend uses (JS Date#getDay()).
DAY_TO_INDEX = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

# Honorifics that appear in front of names but never in lecturer_name_text matches.
_TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms", "miss", "eng", "sir", "madam", "rev"}


def name_query(full_name: str) -> Q | None:
    """
    Same matching as the lecturer dashboard: first AND last name both appear in
    lecturer_name_text (case-insensitive). Titles like "Dr." are dropped first.
    None when there is nothing usable to match on.
    """
    tokens = [t for t in re.split(r"[\s.,]+", full_name or "") if t and t.lower() not in _TITLES]
    if not tokens:
        return None
    if len(tokens) == 1:
        return Q(lecturer_name_text__icontains=tokens[0])
    return Q(lecturer_name_text__icontains=tokens[0]) & Q(lecturer_name_text__icontains=tokens[-1])


def find_lecturer_account(staff_number: str) -> User | None:
    staff_number = (staff_number or "").strip()
    if not staff_number:
        return None
    return User.objects.filter(role=User.Role.LECTURER, university_id__iexact=staff_number).first()


@dataclass
class LecturerUnits:
    term: AcademicTerm | None
    account: User | None
    units: list[dict] = field(default_factory=list)


MAIN_GROUP = "MAIN"


def group_key(class_group: str | None) -> str:
    """
    Formatting-insensitive group identity: "GR A", "GR_A" and "gr a" are one
    group. MAIN (the whole, unsplit class) and blank are "".
    """
    key = re.sub(r"[^A-Z0-9]", "", (class_group or "").upper())
    return "" if key == MAIN_GROUP else key


def group_label(class_group: str | None) -> str:
    """Display form, as it appears in a section code: "GR_A" -> "GR A". "" for MAIN."""
    if not group_key(class_group):
        return ""
    return re.sub(r"[\s_]+", " ", class_group or "").strip().upper()


def section_code(unit_code: str, class_group: str | None) -> str:
    label = group_label(class_group)
    return f"{unit_code} {label}" if label else unit_code


def registered_count(term: AcademicTerm, unit_id, class_group: str | None) -> int:
    """
    Students registered for one class this term: the whole unit for MAIN, else
    only those who picked this group. The lecturer dashboard uses this too.
    """
    rows = StudentUnit.objects.filter(term=term, unit_id=unit_id)
    key = group_key(class_group)
    if not key:
        return rows.values("user_id").distinct().count()
    return sum(1 for cg in rows.values_list("class_group", flat=True) if group_key(cg) == key)


def get_lecturer_units(staff_number: str, fallback_name: str = "") -> LecturerUnits | None:
    """
    The lecturer's timetabled classes in the current term - one per unit and
    teaching group - or None when the lecturer cannot be identified at all (no
    SMARTTT account for the staff number and no name to match slots on).
    """
    account = find_lecturer_account(staff_number)
    full_name = f"{account.first_name} {account.last_name}".strip() if account else ""
    by_name = name_query(full_name or fallback_name)

    if account is None and by_name is None:
        return None

    term = AcademicTerm.objects.filter(is_current=True).first()
    result = LecturerUnits(term=term, account=account)
    if term is None:
        return result

    owner = Q(lecturer__user=account) if account else Q(pk__in=[])
    if by_name is not None:
        owner |= by_name

    slots = (
        TimetableSlot.objects.select_related("unit", "room", "program", "lecturer")
        .filter(Q(term=term) & Q(unit__isnull=False) & owner)
        .order_by("unit__code", "day_of_week", "start_time")
    )

    sections: dict[tuple[str, str], dict] = {}
    seen: set[tuple] = set()
    for slot in slots:
        unit = slot.unit
        key = (str(unit.id), group_key(slot.class_group))
        entry = sections.setdefault(key, {
            "unit_id": unit.id,
            "code": section_code(unit.code, slot.class_group),
            "unit_code": unit.code,
            "group": group_label(slot.class_group) or None,
            "name": unit.name,
            "matched_by": "name",
            "slots": [],
        })
        if account is not None and slot.lecturer is not None and slot.lecturer.user_id == account.id:
            entry["matched_by"] = "account"

        # The same class can be printed once per program sharing it; report it once.
        signature = (key, slot.day_of_week, slot.start_time, slot.end_time, slot.room_id)
        if signature in seen:
            continue
        seen.add(signature)

        day = DAY_TO_INDEX.get((slot.day_of_week or "").strip().lower()[:3])
        if day is None:
            continue
        entry["slots"].append({
            "day_of_week": day,
            "start_time": slot.start_time.strftime("%H:%M"),
            "end_time": slot.end_time.strftime("%H:%M"),
            "room": slot.room.code if slot.room else None,
            "class_group": slot.class_group or "",
            "program": slot.program.name if slot.program else None,
        })

    # day_of_week is stored as text (and not always in one case), so the SQL
    # ordering isn't weekday order; sort each class's slots Monday-first here.
    for entry in sections.values():
        entry["slots"].sort(key=lambda s: ((s["day_of_week"] + 6) % 7, s["start_time"]))

    registrations = _registrations_by_unit(term, {entry["unit_id"] for entry in sections.values()})
    for (unit_id, gkey), entry in sections.items():
        in_unit = registrations.get(unit_id, [])
        if gkey:
            members = [r for r in in_unit if group_key(r.class_group) == gkey]
            entry["students_without_group"] = sum(1 for r in in_unit if not group_key(r.class_group))
        else:
            members = in_unit
            entry["students_without_group"] = 0
        entry["registered_students"] = len({r.user_id for r in members})
        entry["students"] = _roster(members)

    result.units = [
        {k: v for k, v in entry.items() if k != "unit_id"}
        for entry in sorted(sections.values(), key=lambda e: e["code"])
    ]
    return result


def _registrations_by_unit(term: AcademicTerm, unit_ids: set) -> dict[str, list[StudentUnit]]:
    """Every StudentUnit for these units this term, with the student, keyed by str(unit_id)."""
    rows = (
        StudentUnit.objects.filter(term=term, unit_id__in=unit_ids)
        .select_related("user", "user__student_profile")
    )
    result: dict[str, list[StudentUnit]] = {}
    for row in rows:
        result.setdefault(str(row.unit_id), []).append(row)
    return result


def _roster(registrations: list[StudentUnit]) -> list[dict]:
    """
    Registration number and name for each student, sorted by registration
    number, as the attendance roster needs them.

    The registration number is the student's login id (User.university_id,
    their admission number), falling back to their Student profile. A student
    with neither can't be put on an attendance roster, so is left out here;
    `registered_students` still counts them.
    """
    by_number: dict[str, dict] = {}
    for reg in registrations:
        user = reg.user
        profile = getattr(user, "student_profile", None)
        number = (user.university_id or (profile.registration_number if profile else "") or "").strip().upper()
        if not number:
            continue
        name = user.get_full_name().strip()
        if not name and profile:
            name = f"{profile.first_name} {profile.last_name}".strip()
        by_number[number] = {"registration_number": number, "full_name": name or None}
    return sorted(by_number.values(), key=lambda s: s["registration_number"])

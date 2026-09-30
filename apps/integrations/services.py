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


# ---------------------------------------------------------------------------
# Student lookup, for Smart Attendance student registration
# ---------------------------------------------------------------------------

_INACTIVE_STUDENT_STATUSES = {"inactive", "suspended", "graduated", "withdrawn"}


def find_student(registration_number: str) -> dict | None:
    """
    The student with this registration number, as the attendance system needs
    to verify a registration: their name and email on record here, programme,
    and whether they are a current student. None when SMARTTT has no such
    student.

    The registration number is the student's login id (User.university_id),
    falling back to their Student profile's registration_number, the same
    order the roster uses (_roster above).
    """
    number = (registration_number or "").strip()
    user, profile = _find_student_user(number)
    if user is None:
        return None

    name = user.get_full_name().strip()
    if not name and profile:
        name = f"{profile.first_name} {profile.last_name}".strip()
    email = (user.email or (profile.email if profile else "") or "").strip().lower()
    status = (profile.academic_status if profile else "active") or "active"

    return {
        "registration_number": (user.university_id or (profile.registration_number if profile else number)).strip().upper(),
        "full_name": name or None,
        "email": email or None,
        "programme": profile.program.name if profile and profile.program_id else None,
        "year_of_study": profile.current_study_year if profile else None,
        "is_active": bool(user.is_active) and status not in _INACTIVE_STUDENT_STATUSES,
    }


def _find_student_user(number: str):
    """
    (user, Student profile or None) for a registration number: the login id
    (User.university_id) first, then the Student profile's
    registration_number. (None, None) when SMARTTT has no such student.
    """
    if not number:
        return None, None
    user = (
        User.objects.filter(role=User.Role.STUDENT, university_id__iexact=number)
        .select_related("student_profile", "student_profile__program")
        .first()
    )
    if user is not None:
        return user, getattr(user, "student_profile", None)

    from apps.students.models import Student

    profile = (
        Student.objects.filter(registration_number__iexact=number)
        .select_related("user", "program")
        .first()
    )
    return (profile.user, profile) if profile else (None, None)


# ---------------------------------------------------------------------------
# A student's units, for the Smart Attendance student dashboard
# ---------------------------------------------------------------------------


@dataclass
class StudentUnits:
    registration_number: str
    term: AcademicTerm | None
    units: list[dict] = field(default_factory=list)


def get_student_units(registration_number: str) -> StudentUnits | None:
    """
    The classes a student is registered for this term (their StudentUnit
    rows), in the same shape the lecturer side reports them, so the attendance
    system can match each one to the unit its lecturer syncs: one entry per
    section the student sits in, keyed by the same section code
    ("COSC 103 GR A", or "COSC 103" when not split).

    Mirrors get_lecturer_units' rosters: a MAIN section's roster is everyone
    registered for the unit, and a group section's is those who picked that
    group. So a student is in the unit's MAIN section when it has MAIN slots,
    and in their group's section when they have picked one. A split unit
    (only group slots) the student hasn't picked a group for yet is reported
    once, without a group and with `group_required`, so they can be told to
    pick one. A unit with no slots this term is reported as its plain code.

    None when SMARTTT has no student with this registration number.
    """
    number = (registration_number or "").strip()
    user, profile = _find_student_user(number)
    if user is None:
        return None

    reg_number = (user.university_id or (profile.registration_number if profile else number)).strip().upper()
    term = AcademicTerm.objects.filter(is_current=True).first()
    result = StudentUnits(registration_number=reg_number, term=term)
    if term is None:
        return result

    registrations = list(
        StudentUnit.objects.filter(user=user, term=term).select_related("unit").order_by("unit__code")
    )
    slots_by_unit: dict[str, list[TimetableSlot]] = {}
    for slot in (
        TimetableSlot.objects.select_related("room", "program", "lecturer__user")
        .filter(term=term, unit_id__in=[r.unit_id for r in registrations])
        .order_by("day_of_week", "start_time")
    ):
        slots_by_unit.setdefault(str(slot.unit_id), []).append(slot)

    sections: dict[str, dict] = {}
    for reg in registrations:
        unit = reg.unit
        unit_slots = slots_by_unit.get(str(unit.id), [])
        keys = {group_key(s.class_group) for s in unit_slots}
        mine = group_key(reg.class_group)

        wanted: list[str | None] = []  # the class_group label of each section; None for MAIN
        if "" in keys or not keys:
            wanted.append(None)
        if mine and (mine in keys or "" not in keys and keys):
            wanted.append(reg.class_group)
        group_required = not mine and bool(keys) and "" not in keys
        if group_required:
            wanted.append(None)

        for class_group in wanted:
            gkey = group_key(class_group)
            code = section_code(unit.code, class_group)
            if code in sections:
                continue
            section_slots = [s for s in unit_slots if group_key(s.class_group) == gkey] if not group_required else []
            sections[code] = {
                "code": code,
                "unit_code": unit.code,
                "group": group_label(class_group) or None,
                "name": unit.name,
                "group_required": group_required,
                "lecturers": _lecturer_names(section_slots),
                "slots": _slot_list(section_slots),
            }

    result.units = sorted(sections.values(), key=lambda e: e["code"])
    return result


def _lecturer_names(slots: list[TimetableSlot]) -> list[str]:
    """Who teaches these slots: the linked account's name, else the allocation document's."""
    names: dict[str, str] = {}
    for slot in slots:
        name = ""
        if slot.lecturer is not None and slot.lecturer.user is not None:
            name = slot.lecturer.user.get_full_name().strip()
        name = name or (slot.lecturer_name_text or "").strip()
        if name:
            names.setdefault(name.lower(), name)
    return sorted(names.values())


def _slot_list(slots: list[TimetableSlot]) -> list[dict]:
    """Same slot shape as get_lecturer_units, de-duplicated and sorted Monday-first."""
    seen: set[tuple] = set()
    result = []
    for slot in slots:
        day = DAY_TO_INDEX.get((slot.day_of_week or "").strip().lower()[:3])
        if day is None:
            continue
        signature = (day, slot.start_time, slot.end_time, slot.room_id)
        if signature in seen:
            continue
        seen.add(signature)
        result.append({
            "day_of_week": day,
            "start_time": slot.start_time.strftime("%H:%M"),
            "end_time": slot.end_time.strftime("%H:%M"),
            "room": slot.room.code if slot.room else None,
            "class_group": slot.class_group or "",
            "program": slot.program.name if slot.program else None,
        })
    result.sort(key=lambda s: ((s["day_of_week"] + 6) % 7, s["start_time"]))
    return result


# ---------------------------------------------------------------------------
# Staff lookup, for Smart Attendance lecturer registration
# ---------------------------------------------------------------------------


def find_staff(staff_number: str) -> dict | None:
    """
    The lecturer with this staff number, as the attendance system needs to
    verify a lecturer registration. None when the number isn't on the approved
    staff list (accounts.ValidStaffID, the admin's staff-ID CSV uploads).

    The approved list is the authority, the same one SMARTTT's own lecturer
    registration checks: an admin removing an ID deletes it from the list (and
    disables the account using it, see auth_views.revoke_staff_ids), so an ID
    on the list is a current member of staff. The details come from the
    lecturer's SMARTTT account when they have registered one, otherwise from
    the name given in the CSV.
    """
    from apps.accounts.models import ValidStaffID

    number = (staff_number or "").strip()
    if not number:
        return None
    listed = ValidStaffID.objects.filter(staff_id__iexact=number).first()
    if listed is None:
        return None

    account = (
        User.objects.filter(role=User.Role.LECTURER, university_id__iexact=number, is_active=True)
        .select_related("lecturer_profile__department__faculty")
        .first()
    )
    lecturer = getattr(account, "lecturer_profile", None) if account else None
    department = lecturer.department if lecturer else None

    return {
        "staff_number": listed.staff_id.strip().upper(),
        "full_name": (account.get_full_name().strip() if account else "") or listed.name_hint.strip() or None,
        "email": ((account.email or "").strip().lower() if account else "") or None,
        "department": department.name if department else None,
        "faculty": department.faculty.name if department and department.faculty_id else None,
        "title": ((lecturer.rank or "").strip() or None) if lecturer else None,
        "has_account": account is not None,
        "is_active": True,
    }

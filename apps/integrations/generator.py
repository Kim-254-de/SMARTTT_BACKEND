"""
What the Timetable Generator (the Director of Examinations and Timetabling's
solver) reads from SMARTTT, and how a version it publishes is written.

Snapshot (build_snapshot): the read-only master data for a term - rooms,
departments and their lecturer counts, programmes, units, curricula, class
sizes, registrations - plus the term's current timetable with its lecturers,
so a repair re-solve can keep allocated lecturers clash-free (H13).

Publish (publish_version): one numbered version of the term's timetable.

- The whole version is validated before anything is written, then written
  in one transaction.
- Idempotent on (term, version): re-sending the same content returns the
  stored result; different content under a used version number is refused.
- Refused unless `based_on_version` is still the term's latest version, so
  two drafts can't both be published over each other.
- Sessions are matched to existing slots by their stable key, one slot per
  class row the session serves. A slot whose time or room is unchanged keeps
  its row; a moved one is replaced.
- Lecturers belong to SMARTTT (set through the Allocator), not to the
  version: every section (unit + group) keeps its lecturer across versions.
  A version that would put a lecturer in two places at once is refused.
- The first version for a term that still holds uploaded slots (no session
  key) only replaces them when `replace_unpublished` is true.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.departments.models import Department
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetablePublication, TimetableSlot
from apps.units.models import Unit

from .allocator import lecturer_dict, overlaps, section_key, term_dict
from .services import group_key, group_label, section_code

TEACHING_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
DAY_START = time(7, 0)
DAY_END = time(19, 0)
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def build_snapshot(term: AcademicTerm) -> dict:
    lecturers = list(Lecturer.objects.select_related("user", "department").filter(user__is_active=True))
    lecturer_counts: dict[int, dict[str, int]] = defaultdict(lambda: {"full_time": 0, "part_time": 0})
    for lecturer in lecturers:
        lecturer_counts[lecturer.department_id][lecturer.employment_type] += 1

    departments = [
        {
            "id": d.id,
            "code": d.code,
            "name": d.name,
            "faculty": d.faculty.name if d.faculty_id else None,
            "lecturers": dict(lecturer_counts[d.id]),
        }
        for d in Department.objects.filter(status="active").select_related("faculty").order_by("name")
    ]

    rooms = [
        {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "building": r.building,
            "capacity": r.capacity,
            "capacity_confirmed": r.capacity_confirmed,
            "room_type": r.room_type,
            "status": r.status,
        }
        for r in Room.objects.order_by("building", "code")
    ]

    programs = [
        {"id": p.id, "code": p.code, "name": p.name, "department_id": p.department_id,
         "duration_years": p.duration_years}
        for p in Program.objects.filter(status="active").order_by("code")
    ]

    units = [
        {"id": u.id, "code": u.code, "name": u.name, "department_id": u.department_id,
         "credit_hours": float(u.credit_hours)}
        for u in Unit.objects.filter(status="active").order_by("code")
    ]

    curricula: dict[str, dict] = {}
    for cu in (
        CurriculumUnit.objects.filter(
            curriculum__academic_year=term.academic_year, curriculum__status=Curriculum.Status.ACTIVE,
        )
        .select_related("curriculum")
        .order_by("curriculum__program_id", "curriculum__study_year", "curriculum__semester", "display_order")
    ):
        c = cu.curriculum
        entry = curricula.setdefault(str(c.id), {
            "program_id": c.program_id,
            "study_year": c.study_year,
            "study_semester": c.semester,
            "units": [],
        })
        entry["units"].append({
            "unit_id": cu.unit_id,
            "is_core": cu.is_core,
            "is_elective": cu.is_elective,
            "credit_hours": cu.credit_hours,
        })

    from apps.students.models import Student
    from apps.courses.models import StudentUnit

    class_sizes = [
        {"program_id": row["program_id"], "study_year": row["current_study_year"],
         "study_semester": row["current_semester"], "students": row["n"]}
        for row in Student.objects.filter(is_active=True)
        .exclude(academic_status__in=["inactive", "suspended", "graduated", "withdrawn"])
        .values("program_id", "current_study_year", "current_semester")
        .annotate(n=Count("id"))
        .order_by("program_id", "current_study_year", "current_semester")
    ]

    registrations: dict[tuple[int, str], set] = defaultdict(set)
    for unit_id, user_id, class_group in StudentUnit.objects.filter(term=term).values_list(
        "unit_id", "user_id", "class_group"
    ):
        registrations[(unit_id, "")].add(user_id)
        if group_key(class_group):
            registrations[(unit_id, group_label(class_group))].add(user_id)

    latest = TimetablePublication.objects.filter(term=term).order_by("-version").first()
    return {
        "term": term_dict(term),
        "taken_at": timezone.now().isoformat(),
        "teaching_week": {"days": list(TEACHING_DAYS), "start": _hhmm(DAY_START), "end": _hhmm(DAY_END)},
        "departments": departments,
        "lecturers": [lecturer_dict(lecturer) for lecturer in lecturers],
        "rooms": rooms,
        "programs": programs,
        "units": units,
        "curricula": list(curricula.values()),
        "class_sizes": class_sizes,
        "registrations": [
            {"unit_id": unit_id, "group": group or None, "students": len(users)}
            for (unit_id, group), users in sorted(registrations.items(), key=lambda item: (item[0][0], item[0][1]))
        ],
        "published": {
            "version": latest.version if latest else None,
            "sessions": current_sessions(term),
        },
        "warnings": snapshot_warnings(departments, rooms, curricula, programs),
    }


def current_sessions(term: AcademicTerm) -> list[dict]:
    """
    The term's timetable as sessions (one per meeting, with all the class rows
    it serves) and each one's lecturer: published ones by key, uploaded ones
    (no key yet) with `key` None.
    """
    sessions: dict[tuple, dict] = {}
    for slot in (
        TimetableSlot.objects.filter(term=term, unit__isnull=False)
        .select_related("unit", "lecturer")
        .order_by("unit__code", "class_group", "day_of_week", "start_time")
    ):
        identity = (
            ("key", slot.session_key) if slot.session_key
            else ("upload", slot.unit_id, group_key(slot.class_group), slot.day_of_week,
                  slot.start_time, slot.end_time, slot.room_id)
        )
        entry = sessions.setdefault(identity, {
            "key": slot.session_key or None,
            "unit_id": slot.unit_id,
            "group_label": group_label(slot.class_group) or None,
            "section_key": section_key(slot.unit_id, slot.class_group),
            "room_id": str(slot.room_id),
            "day_of_week": (slot.day_of_week or "").upper()[:3],
            "start_time": _hhmm(slot.start_time),
            "end_time": _hhmm(slot.end_time),
            "class_rows": [],
            "lecturer_id": str(slot.lecturer_id) if slot.lecturer_id else None,
        })
        entry["class_rows"].append({
            "program_id": slot.program_id,
            "year_of_study": slot.year_of_study,
            "study_semester": slot.study_semester,
            "stream": slot.stream or "",
        })
    return list(sessions.values())


def snapshot_warnings(departments, rooms, curricula, programs) -> list[dict]:
    """Missing or placeholder data the Director should know about before solving."""
    warnings = []
    for d in departments:
        if not d["lecturers"]["full_time"] and not d["lecturers"]["part_time"]:
            warnings.append({"code": "department_without_lecturers", "department_id": d["id"],
                             "detail": f"{d['name']} has no lecturers in SMARTTT."})
    for r in rooms:
        if not r["capacity_confirmed"] and r["status"] == "active":
            warnings.append({"code": "room_capacity_unconfirmed", "room_id": r["id"],
                             "detail": f"Room {r['code']} capacity ({r['capacity']}) is a placeholder."})
    with_curriculum = {c["program_id"] for c in curricula.values()}
    for p in programs:
        if p["id"] not in with_curriculum:
            warnings.append({"code": "program_without_curriculum", "program_id": p["id"],
                             "detail": f"{p['code']} has no active curriculum for this academic year."})
    return warnings


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class PublishRefused(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status


@dataclass
class PublishResult:
    publication: TimetablePublication
    created: bool
    attendance_changes: list[tuple[str | None, str]] = field(default_factory=list)


def payload_sha256(payload: dict) -> str:
    """Hash of what is published (sessions and version numbers), independent of key order."""
    canonical = {
        "term_id": str(payload.get("term_id")),
        "version": payload.get("version"),
        "based_on_version": payload.get("based_on_version"),
        "sessions": sorted(payload.get("sessions") or [], key=lambda s: str(s.get("key"))),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def publication_dict(publication: TimetablePublication) -> dict:
    return {
        "term_id": str(publication.term_id),
        "version": publication.version,
        "based_on_version": publication.based_on_version,
        "sha256": publication.sha256,
        "published_by": publication.published_by,
        "published_at": publication.created_at.isoformat(),
        "session_count": publication.session_count,
        "slot_count": publication.slot_count,
        "changes": publication.changes,
    }


def _parse_time(value, where: str, errors: list) -> time | None:
    if not isinstance(value, str) or not _TIME_RE.match(value):
        errors.append({"where": where, "detail": "Times must be HH:MM (24-hour)."})
        return None
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


@dataclass
class _Session:
    key: str
    unit: Unit
    class_group: str
    rows: list[tuple]  # (program_id, year_of_study, study_semester, stream)
    room: Room
    day: str
    start: time
    end: time


def _validate(payload: dict, term: AcademicTerm) -> list[_Session]:
    """Every problem with the version at once, or the parsed sessions."""
    errors: list[dict] = []
    raw_sessions = payload.get("sessions")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        raise PublishRefused("invalid", "sessions must be a non-empty list.", status=400)

    unit_ids, room_ids, program_ids = set(), set(), set()
    for raw in raw_sessions:
        if isinstance(raw, dict):
            unit_ids.add(raw.get("unit_id"))
            room_ids.add(str(raw.get("room_id")))
            for row in raw.get("class_rows") or []:
                if isinstance(row, dict):
                    program_ids.add(row.get("program_id"))
    units = {u.id: u for u in Unit.objects.filter(id__in=[i for i in unit_ids if isinstance(i, int)])}
    rooms = {str(room.id): room for room in Room.objects.all()}
    programs = set(Program.objects.filter(id__in=[i for i in program_ids if isinstance(i, int)])
                   .values_list("id", flat=True))

    sessions: list[_Session] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_sessions):
        where = f"sessions[{index}]"
        if not isinstance(raw, dict):
            errors.append({"where": where, "detail": "Each session must be an object."})
            continue
        key = raw.get("key")
        if not isinstance(key, str) or not _KEY_RE.match(key):
            errors.append({"where": where, "detail": "key must be 1-120 letters, digits, '.', '_', ':' or '-'."})
            continue
        where = f"session {key}"
        if key in seen_keys:
            errors.append({"where": where, "detail": "Duplicate session key."})
            continue
        seen_keys.add(key)

        unit = units.get(raw.get("unit_id")) if isinstance(raw.get("unit_id"), int) else None
        if unit is None:
            errors.append({"where": where, "detail": "Unknown unit_id."})
        room = rooms.get(str(raw.get("room_id")))
        if room is None:
            errors.append({"where": where, "detail": "Unknown room_id."})
        elif room.status != Room.Status.ACTIVE:
            errors.append({"where": where, "detail": f"Room {room.code} is {room.status}."})

        label = raw.get("group_label")
        if label is not None and (not isinstance(label, str) or len(label) > 50):
            errors.append({"where": where, "detail": "group_label must be a string of at most 50 characters."})
            label = None
        class_group = group_label(label) if label and group_key(label) else "MAIN"

        day = raw.get("day_of_week")
        if day not in TEACHING_DAYS:
            errors.append({"where": where, "detail": "day_of_week must be one of MON..FRI."})
        start = _parse_time(raw.get("start_time"), where, errors)
        end = _parse_time(raw.get("end_time"), where, errors)
        if start and end:
            if start >= end:
                errors.append({"where": where, "detail": "start_time must be before end_time."})
            elif start < DAY_START or end > DAY_END:
                errors.append({"where": where, "detail": "Teaching is only between 07:00 and 19:00."})

        rows: list[tuple] = []
        raw_rows = raw.get("class_rows")
        if not isinstance(raw_rows, list) or not raw_rows:
            errors.append({"where": where, "detail": "class_rows must be a non-empty list."})
        else:
            for row in raw_rows:
                if not isinstance(row, dict) or row.get("program_id") not in programs:
                    errors.append({"where": where, "detail": "Each class row needs a known program_id."})
                    continue
                year = row.get("year_of_study")
                semester = row.get("study_semester")
                stream = row.get("stream") or ""
                if not isinstance(year, int) or not 1 <= year <= 10:
                    errors.append({"where": where, "detail": "year_of_study must be a whole number 1-10."})
                    continue
                if semester is not None and (not isinstance(semester, int) or not 1 <= semester <= 3):
                    errors.append({"where": where, "detail": "study_semester must be 1, 2, 3 or null."})
                    continue
                if not isinstance(stream, str) or len(stream) > 10:
                    errors.append({"where": where, "detail": "stream must be a string of at most 10 characters."})
                    continue
                identity = (row["program_id"], year, semester, stream.strip())
                if identity in rows:
                    errors.append({"where": where, "detail": "The same class row is listed twice."})
                    continue
                rows.append(identity)

        if unit and room and day in TEACHING_DAYS and start and end and start < end and rows:
            sessions.append(_Session(key=key, unit=unit, class_group=class_group, rows=rows, room=room,
                                     day=day, start=start, end=end))

    if not errors:
        errors.extend(_hard_rule_violations(sessions))
    if errors:
        raise PublishRefused("invalid", "The version breaks the rules below; nothing was published.",
                             {"errors": errors[:200], "error_count": len(errors)}, status=422)
    return sessions


def _hard_rule_violations(sessions: list[_Session]) -> list[dict]:
    """
    H1 (a room hosts one session at a time) and H2 (a class row attends one
    session at a time) across the whole version. Different groups of the same
    unit may share a class row at the same hour: that is one class row split
    across parallel groups, not a double booking.
    """
    errors = []
    by_day: dict[str, list[_Session]] = defaultdict(list)
    for s in sessions:
        by_day[s.day].append(s)
    for day, items in by_day.items():
        items.sort(key=lambda s: s.start)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if b.start >= a.end:
                    break
                if a.room.id == b.room.id:
                    errors.append({"where": f"session {a.key}", "rule": "H1",
                                   "detail": f"Room {a.room.code} also hosts {b.key} on {day}."})
                if a.unit.id != b.unit.id:
                    shared = set(a.rows) & set(b.rows)
                    if shared:
                        errors.append({"where": f"session {a.key}", "rule": "H2",
                                       "detail": f"A class row it serves also attends {b.key} on {day}."})
    return errors


def publish_version(payload: dict) -> PublishResult:
    term_id = payload.get("term_id")
    version = payload.get("version")
    based_on = payload.get("based_on_version")
    published_by = str(payload.get("published_by") or "").strip()
    if not isinstance(version, int) or version < 1:
        raise PublishRefused("invalid", "version must be a whole number from 1.", status=400)
    if based_on is not None and (not isinstance(based_on, int) or based_on < 1):
        raise PublishRefused("invalid", "based_on_version must be a whole number or null.", status=400)
    if not published_by:
        raise PublishRefused("invalid", "published_by is required.", status=400)
    replace_unpublished = payload.get("replace_unpublished") is True
    sha = payload_sha256(payload)

    with transaction.atomic():
        try:
            term = AcademicTerm.objects.select_for_update().filter(pk=term_id).first()
        except (ValueError, TypeError, ValidationError):
            term = None
        if term is None:
            raise PublishRefused("not_found", "No such term.", status=404)

        existing = TimetablePublication.objects.filter(term=term, version=version).first()
        if existing is not None:
            if existing.sha256 == sha:
                return PublishResult(publication=existing, created=False)
            raise PublishRefused("version_taken",
                                 f"Version {version} was already published with different content.")

        latest = TimetablePublication.objects.filter(term=term).order_by("-version").first()
        latest_version = latest.version if latest else None
        if based_on != latest_version:
            raise PublishRefused("stale_base",
                                 f"This draft is based on version {based_on}, but the latest is {latest_version}.",
                                 {"latest_version": latest_version})
        if version <= (latest_version or 0):
            raise PublishRefused("invalid", "version must be higher than the latest published version.",
                                 {"latest_version": latest_version}, status=400)

        sessions = _validate(payload, term)
        return _write(term, version, based_on, sha, published_by, sessions, replace_unpublished)


def _write(term, version, based_on, sha, published_by, sessions, replace_unpublished) -> PublishResult:
    slots = list(
        TimetableSlot.objects.select_for_update()
        .filter(term=term)
        .select_related("unit", "lecturer__user")
    )
    unpublished = [s for s in slots if not s.session_key]
    if unpublished and not replace_unpublished:
        raise PublishRefused(
            "unpublished_slots",
            f"The term still has {len(unpublished)} uploaded slots. Send replace_unpublished: true "
            "to replace them with this version.",
            {"unpublished_slot_count": len(unpublished)},
        )

    # Each section keeps its lecturer on new and moved slots; an uploaded
    # slot's lecturer carries over too.
    section_lecturers: dict[str, tuple] = {}
    for slot in slots:
        if slot.unit_id and (slot.lecturer_id or slot.lecturer_name_text):
            section_lecturers.setdefault(
                section_key(slot.unit_id, slot.class_group), (slot.lecturer, slot.lecturer_name_text)
            )

    _check_lecturer_clashes(sessions, section_lecturers)

    publication = TimetablePublication.objects.create(
        term=term, version=version, based_on_version=based_on, sha256=sha, published_by=published_by[:255],
    )

    existing_by_identity = {}
    for slot in slots:
        if slot.session_key:
            identity = (slot.session_key, slot.program_id, slot.year_of_study, slot.stream or "")
            existing_by_identity[identity] = slot
    old_keys = {s.session_key for s in slots if s.session_key}
    old_where = {
        s.session_key: (s.unit_id, group_key(s.class_group), s.day_of_week, s.start_time, s.end_time, s.room_id)
        for s in slots if s.session_key
    }

    to_create: list[TimetableSlot] = []
    to_update: list[TimetableSlot] = []
    kept_ids: set = set()
    for s in sessions:
        lecturer, name_text = section_lecturers.get(section_key(s.unit.id, s.class_group), (None, ""))
        for program_id, year, semester, stream in s.rows:
            slot = existing_by_identity.get((s.key, program_id, year, stream))
            fields = dict(
                unit=s.unit, class_group=s.class_group, room=s.room, day_of_week=s.day.lower(),
                start_time=s.start, end_time=s.end,
            )
            unchanged = slot is not None and (
                slot.unit_id == s.unit.id and slot.class_group == s.class_group and slot.room_id == s.room.id
                and slot.day_of_week == s.day.lower() and slot.start_time == s.start and slot.end_time == s.end
            )
            if unchanged:
                # Same class, same place: the row and its lecturer stay as they are.
                kept_ids.add(slot.id)
                slot.study_semester = semester
                slot.publication = publication
                to_update.append(slot)
            else:
                to_create.append(TimetableSlot(
                    term=term, program_id=program_id, year_of_study=year, study_semester=semester,
                    stream=stream, session_key=s.key, publication=publication,
                    lecturer=lecturer, lecturer_name_text=name_text, **fields,
                ))
    to_delete = [slot.id for slot in slots if slot.id not in kept_ids]

    # Deletes first, so a session moving onto a spot another vacates never
    # trips the slot uniqueness constraint.
    TimetableSlot.objects.filter(id__in=to_delete).delete()
    TimetableSlot.objects.bulk_update(
        to_update, ["study_semester", "publication"], batch_size=500
    )
    TimetableSlot.objects.bulk_create(to_create, batch_size=500)

    new_where = {
        s.key: (s.unit.id, group_key(s.class_group), s.day.lower(), s.start, s.end, s.room.id) for s in sessions
    }
    added = sorted(set(new_where) - old_keys)
    removed = sorted(old_keys - set(new_where))
    moved = sorted(k for k in set(new_where) & old_keys if new_where[k] != old_where[k])
    unchanged_count = len(set(new_where) & old_keys) - len(moved)
    publication.session_count = len(sessions)
    publication.slot_count = len(to_update) + len(to_create)
    publication.changes = {
        "added": added,
        "moved": moved,
        "removed": removed,
        "unchanged": unchanged_count,
        "replaced_unpublished_slots": len(unpublished),
    }
    publication.save(update_fields=["session_count", "slot_count", "changes", "updated_at"])

    return PublishResult(
        publication=publication,
        created=True,
        attendance_changes=_attendance_changes(slots, sessions, set(added) | set(moved) | set(removed),
                                               section_lecturers, bool(unpublished)),
    )


def _check_lecturer_clashes(sessions: list[_Session], section_lecturers: dict) -> None:
    """H13: no lecturer kept on a section may end up teaching two sessions at once."""
    by_lecturer: dict = defaultdict(list)
    for s in sessions:
        lecturer, _name = section_lecturers.get(section_key(s.unit.id, s.class_group), (None, ""))
        if lecturer is not None:
            by_lecturer[lecturer].append(s)
    clashes = []
    for lecturer, items in by_lecturer.items():
        meetings = [
            {"key": s.key, "section": section_key(s.unit.id, s.class_group), "day_of_week": s.day,
             "start_time": _hhmm(s.start), "end_time": _hhmm(s.end)}
            for s in items
        ]
        for i, a in enumerate(meetings):
            for b in meetings[i + 1:]:
                if a["section"] != b["section"] and overlaps(a, b):
                    clashes.append({
                        "lecturer_id": str(lecturer.id),
                        "lecturer": lecturer.user.get_full_name().strip(),
                        "sessions": [a["key"], b["key"]],
                        "day_of_week": a["day_of_week"],
                    })
    if clashes:
        raise PublishRefused(
            "lecturer_clash",
            "The version puts an allocated lecturer in two classes at once; nothing was published.",
            {"clashes": clashes[:200]},
        )


def _attendance_changes(old_slots, sessions, changed_keys, section_lecturers, replaced_uploads) -> list:
    """(staff number, section code) for every class that moved, appeared or went away."""
    changes = []
    for s in sessions:
        if s.key in changed_keys or replaced_uploads:
            lecturer, _ = section_lecturers.get(section_key(s.unit.id, s.class_group), (None, ""))
            staff = lecturer.user.university_id if lecturer else None
            changes.append((staff, section_code(s.unit.code, s.class_group)))
    for slot in old_slots:
        if slot.unit_id and (slot.session_key in changed_keys or not slot.session_key):
            staff = slot.lecturer.user.university_id if slot.lecturer_id else None
            changes.append((staff, section_code(slot.unit.code, slot.class_group)))
    return changes


def latest_publication(term: AcademicTerm) -> TimetablePublication | None:
    return TimetablePublication.objects.filter(term=term).order_by("-version").first()

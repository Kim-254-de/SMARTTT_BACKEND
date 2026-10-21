"""
The Timetable Generator publishes the Directorate's approved timetable here,
as the term's master timetable: what students and lecturers see in the app,
what lecturer allocations are applied to, and what Smart Attendance lets
classes be activated in. It replaces uploading the timetable as a PDF.

POST /api/v1/integrations/generator/publish/   (X-API-Key = GENERATOR_API_KEY)

    {
      "term_id": "<SMARTTT term uuid>" | null,      # null: found (or created) by year and semester
      "academic_year": "2026/2027", "semester": 1,
      "term_start": "2026-09-07", "term_end": "2026-12-18",   # needed only to create the term
      "version": 2, "based_on_version": 1,
      "published_by": "Dee Director (STF/0900)",
      "replace_unpublished": false,
      "sessions": [{
        "key": "COSC103-GRA-1",
        "unit_id": 412 | null, "unit_code": "COSC 103", "unit_name": "Computer Applications",
        "weekly_hours": 3,
        "department": {"smarttt_id": 7 | null, "code": "DCOMP", "name": "Computer Science"},
        "group_label": "GR A" | null,
        "room": {"code": "STB 1", "building": "STB", "capacity": 120, "room_type": "lecture_hall"},
        "day_of_week": "TUE", "start_time": "10:00", "end_time": "12:00",
        "class_rows": [{"label": "BED.ARTS Y1S1", "program_id": null, "program_code": "BED.ARTS",
                        "year_of_study": 1, "study_semester": 1, "stream": "",
                        "department_smarttt_id": 9 | null}]
      }]
    }

One TimetableSlot per session per class row, keyed by `generator_key`
("<session key>|<class row>"), so a later version updates the same slot in
place: a lecturer allocated to it stays, and only what moved changes.

Rules, all checked before anything is written, in one transaction:
- versions only go up: `based_on_version` must be the term's latest
  (409 stale_base); re-sending a version with the same sessions answers 200
  with the stored result, with different ones 409 version_taken;
- the first publish over a term holding uploaded (non-Generator) slots must
  say `replace_unpublished` (409 unpublished_slots), so an upload is never
  wiped by accident;
- Monday-Friday, 07:00-19:00, and no room holds two classes at once (422);
- units, rooms and programmes SMARTTT doesn't have are created from what the
  Generator sends (code, name, the owning department, capacity and type),
  never invented; a department not yet in SMARTTT is refused (422).

After it is saved, the year's lecturer allocation documents are re-applied
(as after a PDF upload), cached personal timetables are cleared, and Smart
Attendance is told which lecturers' classes moved.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.departments.models import Department
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetablePublication, TimetableSlot
from apps.units.models import Unit

from .attendance_push import queue_timetable_changes, timetable_change_payload

logger = logging.getLogger(__name__)

DAYS = ("MON", "TUE", "WED", "THU", "FRI")
FIRST_HOUR, LAST_HOUR = time(7, 0), time(19, 0)


class PublishRefused(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra):
        super().__init__(detail)
        self.status = status
        self.body = {"code": code, "detail": detail, **extra}


# -- the payload -----------------------------------------------------------------------------


class _Department(serializers.Serializer):
    smarttt_id = serializers.IntegerField(allow_null=True, required=False)
    code = serializers.CharField(allow_blank=True, required=False, default="")
    name = serializers.CharField(allow_blank=True, required=False, default="")


class _Room(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    building = serializers.CharField(allow_blank=True, required=False, default="")
    capacity = serializers.IntegerField(min_value=1)
    room_type = serializers.ChoiceField(choices=[c for c, _ in Room.Type.choices])


class _ClassRow(serializers.Serializer):
    label = serializers.CharField(max_length=120)
    program_id = serializers.IntegerField(allow_null=True, required=False)
    program_code = serializers.CharField(max_length=64)
    year_of_study = serializers.IntegerField(min_value=1, max_value=7)
    study_semester = serializers.IntegerField(min_value=1, max_value=3, required=False)
    stream = serializers.CharField(max_length=10, allow_blank=True, required=False, default="")
    department_smarttt_id = serializers.IntegerField(allow_null=True, required=False)


class _Session(serializers.Serializer):
    key = serializers.CharField(max_length=120)
    unit_id = serializers.IntegerField(allow_null=True, required=False)
    unit_code = serializers.CharField(max_length=64)
    unit_name = serializers.CharField(max_length=255)
    weekly_hours = serializers.IntegerField(min_value=1, max_value=40, required=False, allow_null=True)
    department = _Department()
    group_label = serializers.CharField(max_length=50, allow_null=True, allow_blank=True, required=False)
    room = _Room()
    day_of_week = serializers.ChoiceField(choices=DAYS)
    start_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    end_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    class_rows = _ClassRow(many=True, allow_empty=False)


class PublishSerializer(serializers.Serializer):
    term_id = serializers.UUIDField(allow_null=True, required=False)
    academic_year = serializers.RegexField(r"^\d{4}/\d{4}$")
    semester = serializers.IntegerField(min_value=1, max_value=3)
    term_start = serializers.DateField(allow_null=True, required=False)
    term_end = serializers.DateField(allow_null=True, required=False)
    version = serializers.IntegerField(min_value=1)
    based_on_version = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    published_by = serializers.CharField(max_length=255)
    replace_unpublished = serializers.BooleanField(default=False)
    sessions = _Session(many=True, allow_empty=False)


# -- helpers -----------------------------------------------------------------------------------


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def class_group(group_label: str | None) -> str:
    """SMARTTT's form: "GR A" -> "GR_A"; no group (a whole class) -> "MAIN"."""
    label = re.sub(r"\s+", " ", (group_label or "").strip().upper())
    return label.replace(" ", "_") if label else "MAIN"


def _sha(data: dict) -> str:
    return hashlib.sha256(json.dumps(data["sessions"], sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class _Wanted:
    """One slot the version needs."""

    key: str
    session_key: str
    unit: Unit
    program: Program
    year_of_study: int
    room: Room
    day_of_week: str
    start_time: time
    end_time: time
    class_group: str
    stream: str

    def identity(self) -> tuple:
        """The fields SMARTTT's unique_timetable_slot constraint covers (term aside)."""
        return (
            self.program.pk, self.unit.pk, self.year_of_study, self.day_of_week,
            self.start_time, self.end_time, self.room.pk, self.class_group, self.stream,
        )


@dataclass
class _Created:
    units: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)


# -- publishing ----------------------------------------------------------------------------------


def publish(data: dict) -> tuple[int, dict]:
    """(HTTP status, body). Raises PublishRefused when nothing may be written."""
    sha = _sha(data)
    with transaction.atomic():
        term = _term(data)
        # One publish per term at a time: the version check below holds while this runs.
        AcademicTerm.objects.select_for_update().filter(pk=term.pk).first()

        existing = TimetablePublication.objects.filter(term=term, version=data["version"]).first()
        if existing is not None:
            if existing.payload_sha256 == sha:
                return 200, existing.result
            raise PublishRefused(409, "version_taken", f"Version {data['version']} was already published with other classes.")
        latest = TimetablePublication.objects.filter(term=term).order_by("-version").first()
        latest_version = latest.version if latest else None
        if data.get("based_on_version") != latest_version or (latest_version and data["version"] <= latest_version):
            raise PublishRefused(
                409,
                "stale_base",
                f"SMARTTT has version {latest_version} of this term; this one was made from "
                f"{data.get('based_on_version')}. Publish from the latest version.",
                latest_version=latest_version,
            )

        uploaded = TimetableSlot.objects.filter(term=term, generator_key="")
        uploaded_count = uploaded.count()
        if uploaded_count and not data["replace_unpublished"]:
            raise PublishRefused(
                409,
                "unpublished_slots",
                f"{term} has {uploaded_count} timetable slots that were uploaded, not published by the Generator. "
                "Confirm they should be replaced.",
                unpublished_slots=uploaded_count,
            )

        _check_rules(data["sessions"])
        created = _Created()
        wanted = _wanted_slots(data["sessions"], created)
        changes, changed_payloads = _apply(term, wanted, replace_uploaded=uploaded_count > 0)
        # SMARTTT's id for each unit, so the Generator can link the ones it entered itself.
        units = {
            next(s["unit_code"] for s in data["sessions"] if s["key"] == w.session_key): w.unit.pk
            for w in wanted.values()
        }
        result = {
            "term_id": str(term.pk),
            "academic_year": term.academic_year,
            "semester": term.semester,
            "version": data["version"],
            "based_on_version": data.get("based_on_version"),
            "session_count": len(data["sessions"]),
            "slot_count": len(wanted),
            "changes": changes,
            "replaced_uploaded_slots": uploaded_count,
            "created": {"units": created.units, "rooms": created.rooms, "programs": created.programs},
            "units": units,
        }
        TimetablePublication.objects.create(
            term=term,
            version=data["version"],
            based_on_version=data.get("based_on_version"),
            published_by=data["published_by"],
            payload_sha256=sha,
            session_count=len(data["sessions"]),
            slot_count=len(wanted),
            result=result,
        )
        queue_timetable_changes(changed_payloads)

    _after_publish(term)
    return 201, result


def _term(data: dict) -> AcademicTerm:
    if data.get("term_id"):
        term = AcademicTerm.objects.filter(pk=data["term_id"]).first()
        if term is None:
            raise PublishRefused(404, "unknown_term", "SMARTTT has no such term.")
        if (term.academic_year, term.semester) != (data["academic_year"], data["semester"]):
            raise PublishRefused(
                422,
                "term_mismatch",
                f"That term is {term.academic_year} semester {term.semester}, not "
                f"{data['academic_year']} semester {data['semester']}.",
            )
        return term
    term = AcademicTerm.objects.filter(academic_year=data["academic_year"], semester=data["semester"]).first()
    if term is not None:
        return term
    start, end = data.get("term_start"), data.get("term_end")
    if not isinstance(start, date) or not isinstance(end, date) or end <= start:
        raise PublishRefused(
            422,
            "term_dates_required",
            f"SMARTTT has no {data['academic_year']} semester {data['semester']} yet. Give the term its start "
            "and end dates in the Generator so it can be created.",
        )
    return AcademicTerm.objects.create(
        academic_year=data["academic_year"], semester=data["semester"], start_date=start, end_date=end
    )


def _check_rules(sessions: list[dict]) -> None:
    problems: list[str] = []
    keys = [s["key"] for s in sessions]
    if len(set(keys)) != len(keys):
        problems.append("Some session keys are repeated.")
    by_room: dict[tuple[str, str], list[dict]] = {}
    for s in sessions:
        if not (FIRST_HOUR <= s["start_time"] < s["end_time"] <= LAST_HOUR):
            problems.append(f"{s['key']}: classes run Monday-Friday between 07:00 and 19:00.")
        by_room.setdefault((compact(s["room"]["code"]), s["day_of_week"]), []).append(s)
    for (_room, day), held in by_room.items():
        held.sort(key=lambda s: s["start_time"])
        for a, b in zip(held, held[1:]):
            if b["start_time"] < a["end_time"]:
                problems.append(f"{a['room']['code']} holds {a['key']} and {b['key']} at once on {day}.")
    if problems:
        raise PublishRefused(422, "invalid_timetable", problems[0], problems=problems[:50])


def _department(smarttt_id: int | None, label: str, departments: dict[int, Department]) -> Department:
    if smarttt_id is None or smarttt_id not in departments:
        found = Department.objects.filter(pk=smarttt_id).first() if smarttt_id is not None else None
        if found is None:
            raise PublishRefused(
                422,
                "unknown_department",
                f"{label} is not a SMARTTT department yet. It must reach SMARTTT (through Smart Attendance) "
                "before its classes can be published.",
            )
        departments[smarttt_id] = found
    return departments[smarttt_id]


def _wanted_slots(sessions: list[dict], created: _Created) -> dict[str, _Wanted]:
    departments: dict[int, Department] = {}
    units: dict[str, Unit] = {}
    rooms: dict[str, Room] = {}
    programs: dict[tuple[str, int | None], Program] = {}
    rooms_by_code = {compact(r.code): r for r in Room.objects.all()}

    def unit_for(s: dict) -> Unit:
        code = compact(s["unit_code"])
        if code in units:
            return units[code]
        unit = Unit.objects.filter(pk=s["unit_id"]).first() if s.get("unit_id") else None
        if unit is None:
            department = s["department"].get("smarttt_id")
            candidates = [u for u in Unit.objects.filter(code__iexact=s["unit_code"].strip())] or [
                u for u in Unit.objects.all() if compact(u.code) == code
            ]
            unit = next((u for u in candidates if u.department_id == department), None) or (
                candidates[0] if len(candidates) == 1 else None
            )
        if unit is None:
            owner = _department(s["department"].get("smarttt_id"), s["department"].get("name") or s["unit_code"], departments)
            unit = Unit.objects.create(
                code=s["unit_code"].strip(),
                name=s["unit_name"].strip()[:255],
                credit_hours=Decimal(s.get("weekly_hours") or 0),
                department=owner,
            )
            created.units.append(unit.code)
        units[code] = unit
        return unit

    def room_for(s: dict) -> Room:
        room = s["room"]
        code = compact(room["code"])
        if code not in rooms:
            found = rooms_by_code.get(code)
            if found is None:
                found = Room.objects.create(
                    code=room["code"].strip(),
                    name=room["code"].strip(),
                    building=room.get("building") or "",
                    capacity=room["capacity"],
                    capacity_confirmed=True,
                    room_type=room["room_type"],
                )
                rooms_by_code[code] = found
                created.rooms.append(found.code)
            rooms[code] = found
        return rooms[code]

    def program_for(row: dict) -> Program:
        key = (compact(row["program_code"]), row.get("program_id"))
        if key in programs:
            return programs[key]
        program = Program.objects.filter(pk=row["program_id"]).first() if row.get("program_id") else None
        if program is None:
            candidates = list(Program.objects.filter(code__iexact=row["program_code"].strip())) or [
                p for p in Program.objects.all() if compact(p.code) == key[0]
            ]
            dept = row.get("department_smarttt_id")
            program = next((p for p in candidates if p.department_id == dept), None) or (
                candidates[0] if candidates else None
            )
        if program is None:
            owner = _department(row.get("department_smarttt_id"), f"The department of {row['label']}", departments)
            code = row["program_code"].strip()
            program = Program.objects.create(code=code, name=code, department=owner)
            created.programs.append(program.code)
        programs[key] = program
        return program

    wanted: dict[str, _Wanted] = {}
    seen: set[tuple] = set()
    for s in sessions:
        unit, room = unit_for(s), room_for(s)
        for row in s["class_rows"]:
            w = _Wanted(
                key=f"{s['key']}|{compact(row['label'])}"[:160],
                session_key=s["key"],
                unit=unit,
                program=program_for(row),
                year_of_study=row["year_of_study"],
                room=room,
                day_of_week=s["day_of_week"].lower(),
                start_time=s["start_time"],
                end_time=s["end_time"],
                class_group=class_group(s.get("group_label")),
                stream=(row.get("stream") or "").strip()[:10],
            )
            # Two class rows SMARTTT can't tell apart (e.g. one programme's
            # year in two study semesters) attend the same class: one slot.
            if w.identity() in seen:
                continue
            seen.add(w.identity())
            wanted[w.key] = w
    return wanted


SLOT_FIELDS = ("unit", "program", "year_of_study", "room", "day_of_week", "start_time", "end_time", "class_group", "stream")
WHERE_FIELDS = ("room", "day_of_week", "start_time", "end_time")


def _apply(term: AcademicTerm, wanted: dict[str, _Wanted], replace_uploaded: bool) -> tuple[dict, list[dict]]:
    """Writes the version: updates kept slots in place, adds new ones, removes the rest."""
    current = {s.generator_key: s for s in TimetableSlot.objects.select_related("unit", "lecturer__user").filter(term=term).exclude(generator_key="")}
    payloads: list[dict] = []

    # Removed first, so a class moving into a freed place never meets SMARTTT's
    # unique constraint. Lecturers who taught a removed class are told.
    removed = [s for k, s in current.items() if k not in wanted]
    if replace_uploaded:
        removed += list(TimetableSlot.objects.select_related("unit", "lecturer__user").filter(term=term, generator_key=""))
    payloads += [timetable_change_payload(s) for s in removed if s.lecturer_id]
    TimetableSlot.objects.filter(pk__in=[s.pk for s in removed]).delete()

    to_update: list[TimetableSlot] = []
    moved: set[str] = set()
    unchanged: set[str] = set()
    for key, w in wanted.items():
        slot = current.get(key)
        if slot is None:
            continue
        values = {f: getattr(w, f) for f in SLOT_FIELDS}
        if all(getattr(slot, f) == v for f, v in values.items()):
            unchanged.add(w.session_key)
            continue
        # The lecturer's class as it was and, renamed (another unit or group), as it is now.
        renamed = slot.class_group != w.class_group or slot.unit_id != w.unit.pk
        if slot.lecturer_id:
            payloads.append(timetable_change_payload(slot))
        moved.add(w.session_key)
        for f, v in values.items():
            setattr(slot, f, v)
        to_update.append(slot)
        if slot.lecturer_id and renamed:
            payloads.append(timetable_change_payload(slot))

    if to_update:
        # Kept slots may swap places (A takes B's hour and room as B moves on):
        # park them on values no other slot has first, so SMARTTT's unique
        # constraint never sees two at once mid-update.
        final_groups = {s.pk: s.class_group for s in to_update}
        for s in to_update:
            s.class_group = f"~{uuid.uuid4().hex}"
        TimetableSlot.objects.bulk_update(to_update, ["class_group"])
        for s in to_update:
            s.class_group = final_groups[s.pk]
        TimetableSlot.objects.bulk_update(to_update, list(SLOT_FIELDS))

    added = [w for k, w in wanted.items() if k not in current]
    TimetableSlot.objects.bulk_create(
        [
            TimetableSlot(term=term, generator_key=w.key, **{f: getattr(w, f) for f in SLOT_FIELDS})
            for w in added
        ],
        batch_size=500,
    )

    # By session (one session is a slot per class row): a session is moved
    # when any of its slots changed, removed when none of its slots is left.
    still_there = {w.session_key for w in wanted.values()}
    added_keys = sorted({w.session_key for w in added} - moved - unchanged)
    changes = {
        "added": added_keys,
        "moved": sorted(moved),
        "removed": sorted({k.split("|")[0] for k in current if k not in wanted} - still_there),
        "unchanged": len(unchanged - moved - set(added_keys)),
    }
    return changes, payloads


def _after_publish(term: AcademicTerm) -> None:
    """As after a PDF upload: lecturer allocations onto the new slots, fresh personal timetables. Never fails the publish."""
    try:
        from apps.common.services.cache_service import PersonalizationCacheService
        from apps.timetable.services.allocation_service import reapply_allocations

        applied = reapply_allocations(term.academic_year)
        if applied is not None:
            logger.info("generator publish: re-applied lecturer allocations to %s slot(s)", applied["updated"])
        PersonalizationCacheService.clear_all()
    except Exception:
        logger.exception("generator publish: could not re-apply lecturer allocations for %s", term)

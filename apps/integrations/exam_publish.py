"""
The Timetable Generator publishes the Director's approved exam timetable here.

POST /api/v1/integrations/generator/exam-publish/   (X-API-Key = GENERATOR_API_KEY)

    {
      "term_id": "<SMARTTT term uuid>",
      "version": 2, "based_on_version": 1,
      "published_by": "Dee Director (STF/0900)",
      "exam_start": "2026-11-23", "exam_end": "2026-12-04",          # optional: the exam period
      "rooms": [{"code": "UTC 1", "building": "UTC", "capacity": 300, "exam_seats": 270}],   # optional
      "papers": [{
        "key": "p-7f3a", "unit_codes": ["BITE 131", "COSC 130"], "title": "Programming",
        "date": "2026-11-23", "start_time": "08:30", "end_time": "10:30",
        "examiner_staff_number": "STF/0001",
        "sitting": "regular",                          # optional: "odel" for the ODEL / part-time paper
        "seating": [{
          "room_code": "UTC 1",
          "class_rows": [{"program": "BSC.CS", "year_of_study": 1, "study_semester": 1, "stream": ""}],
          "reg_from": null, "reg_to": null,          # or a registration-number range
          "part": 1, "parts": 2,                     # a class row split over rooms: SMARTTT cuts its students by reg number
          "students": 120, "invigilator_staff_number": "STF/0002", "role": "main"
        }]
      }],
      "practicals": [{"unit_codes": ["COSC 200"], "title": "Data", "date": "2026-11-20", "start_time": "09:00", "end_time": "11:00"}]
    }

Refusals write nothing: 404 unknown_term; 409 stale_base | version_taken;
422 invalid (with `problems`), unknown_lecturer (with `staff_numbers`),
unknown_room (with `rooms`). Re-sending a version with the same papers
answers 200 with the stored result. The result says what changed against
the previous version (papers added, removed, moved, rooms changed,
invigilators changed); once the term is in exam mode those changes are
notified to the people affected and sent to Smart Attendance.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, time
from typing import Any

from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, ExamPaper, ExamPublication, ExamSeating, Practical

from .services import find_lecturer_account

logger = logging.getLogger(__name__)

# The three exam sessions of a day (start, end); EXAM_SESSIONS in settings overrides them.
DEFAULT_SESSIONS = (("08:30", "10:30"), ("11:30", "13:30"), ("14:30", "16:30"))


def exam_sessions() -> list[tuple[time, time]]:
    pairs = getattr(settings, "EXAM_SESSIONS", None) or DEFAULT_SESSIONS
    return [(time.fromisoformat(a), time.fromisoformat(b)) for a, b in pairs]


class ExamPublishRefused(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status = status
        self.body = {"code": code, "detail": detail, **extra}


# -- the payload -----------------------------------------------------------------------------


class _ClassRow(serializers.Serializer):
    program = serializers.CharField(max_length=64)
    year_of_study = serializers.IntegerField(min_value=1, max_value=7)
    study_semester = serializers.IntegerField(min_value=1, max_value=3, required=False, allow_null=True)
    stream = serializers.CharField(max_length=10, allow_blank=True, required=False, default="")


class _Seating(serializers.Serializer):
    room_code = serializers.CharField(max_length=30)
    class_rows = _ClassRow(many=True, allow_empty=False)
    reg_from = serializers.CharField(max_length=50, allow_null=True, allow_blank=True, required=False)
    reg_to = serializers.CharField(max_length=50, allow_null=True, allow_blank=True, required=False)
    part = serializers.IntegerField(min_value=1, required=False, default=1)
    parts = serializers.IntegerField(min_value=1, required=False, default=1)
    students = serializers.IntegerField(min_value=1)
    invigilator_staff_number = serializers.CharField(max_length=64, allow_blank=True)
    role = serializers.ChoiceField(choices=[c for c, _ in ExamSeating.Role.choices])


class _Paper(serializers.Serializer):
    key = serializers.CharField(max_length=120)
    unit_codes = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=False)
    title = serializers.CharField(max_length=255)
    date = serializers.DateField()
    start_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    end_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    examiner_staff_number = serializers.CharField(max_length=64, allow_null=True, allow_blank=True, required=False)
    sitting = serializers.ChoiceField(choices=["regular", "odel"], required=False, default="regular")
    # Empty for a paper nobody is known to sit yet (e.g. part-time students who never synced): it has a
    # date and session, and its room is to be announced.
    seating = _Seating(many=True, allow_empty=True)


class _Room(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    building = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    capacity = serializers.IntegerField(min_value=1)
    exam_seats = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class _Practical(serializers.Serializer):
    unit_codes = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=False)
    title = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    date = serializers.DateField()
    start_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    end_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])


class ExamPublishSerializer(serializers.Serializer):
    term_id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=1)
    based_on_version = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    published_by = serializers.CharField(max_length=255)
    exam_start = serializers.DateField(required=False, allow_null=True)
    exam_end = serializers.DateField(required=False, allow_null=True)
    rooms = _Room(many=True, required=False, default=list)
    papers = _Paper(many=True, allow_empty=False)
    practicals = _Practical(many=True, required=False, default=list)


def _sha(data: dict) -> str:
    body = {"papers": data["papers"], "practicals": data.get("practicals") or []}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


# -- publishing ------------------------------------------------------------------------------


def publish(data: dict) -> tuple[int, dict]:
    """(HTTP status, body). Raises ExamPublishRefused when nothing may be written."""
    sha = _sha(data)
    with transaction.atomic():
        term = AcademicTerm.objects.select_for_update().filter(pk=data["term_id"]).first()
        if term is None:
            raise ExamPublishRefused(404, "unknown_term", "SMARTTT has no such term.")
        existing = ExamPublication.objects.filter(term=term, version=data["version"]).first()
        if existing is not None:
            if existing.payload_sha256 == sha:
                return 200, existing.result
            raise ExamPublishRefused(
                409, "version_taken", f"Exam version {data['version']} was already published with other papers."
            )
        previous = ExamPublication.objects.filter(term=term).order_by("-version").first()
        latest = previous.version if previous else None
        if data.get("based_on_version") != latest or (latest and data["version"] <= latest):
            raise ExamPublishRefused(
                409,
                "stale_base",
                f"SMARTTT has exam version {latest} of this term; this one was made from "
                f"{data.get('based_on_version')}. Publish from the latest version.",
                latest_version=latest,
            )
        rooms = _rooms(data)
        _check(term, data, rooms)

        publication = ExamPublication.objects.create(
            term=term,
            version=data["version"],
            based_on_version=data.get("based_on_version"),
            published_by=data["published_by"],
            payload_sha256=sha,
            exam_start=data.get("exam_start"),
            exam_end=data.get("exam_end"),
        )
        for p in data["papers"]:
            paper = ExamPaper.objects.create(
                publication=publication,
                key=p["key"],
                unit_codes=list(p["unit_codes"]),
                title=p["title"],
                date=p["date"],
                start_time=p["start_time"],
                end_time=p["end_time"],
                examiner_staff_number=(p.get("examiner_staff_number") or "").strip().upper(),
                sitting=p.get("sitting") or ExamPaper.Sitting.REGULAR,
            )
            ExamSeating.objects.bulk_create(
                ExamSeating(
                    paper=paper,
                    room=rooms[_code(s["room_code"])],
                    class_rows=[dict(r) for r in s["class_rows"]],
                    reg_from=(s.get("reg_from") or "").strip(),
                    reg_to=(s.get("reg_to") or "").strip(),
                    part=s.get("part") or 1,
                    parts=s.get("parts") or 1,
                    students=s["students"],
                    invigilator_staff_number=s["invigilator_staff_number"].strip().upper(),
                    role=s["role"],
                )
                for s in p["seating"]
            )
        Practical.objects.bulk_create(
            Practical(
                publication=publication,
                unit_codes=list(pr["unit_codes"]),
                title=pr.get("title") or "",
                date=pr["date"],
                start_time=pr["start_time"],
                end_time=pr["end_time"],
            )
            for pr in data.get("practicals") or []
        )
        changes = compare(previous, publication)
        publication.result = {
            "term_id": str(term.pk),
            "version": publication.version,
            "based_on_version": publication.based_on_version,
            "papers": len(data["papers"]),
            "seatings": sum(len(p["seating"]) for p in data["papers"]),
            "practicals": len(data.get("practicals") or []),
            "mode": term.mode,
            "changes": changes,
        }
        publication.save(update_fields=["result"])

    if term.in_exam_mode:
        _after_change(term, previous, publication, changes)
    return 201, publication.result


def _after_change(term: AcademicTerm, previous: ExamPublication | None, publication: ExamPublication, changes: dict) -> None:
    """In exam mode: tell the people affected, and Smart Attendance, at once. Never fails the publish."""
    try:
        from .attendance_push import push_exam_sessions
        from .exam_notifications import notify_changes

        notify_changes(term, previous, publication, changes)
        push_exam_sessions(publication)
    except Exception:
        logger.exception("exam publish: could not notify the changes of %s", publication)


def _code(value: str) -> str:
    return " ".join((value or "").split()).upper()


def _rooms(data: dict) -> dict[str, Room]:
    """Each room the papers use, by code; a room sent in `rooms` that SMARTTT lacks is created."""
    wanted = {_code(s["room_code"]) for p in data["papers"] for s in p["seating"]}
    sent = {_code(r["code"]): r for r in data.get("rooms") or []}
    found = {_code(r.code): r for r in Room.objects.all() if _code(r.code) in wanted}
    missing = sorted(wanted - set(found) - set(sent))
    if missing:
        raise ExamPublishRefused(
            422, "unknown_room", f"SMARTTT doesn't know {len(missing)} rooms: {', '.join(missing[:10])}.", rooms=missing
        )
    for code in sorted(wanted - set(found)):
        r = sent[code]
        found[code] = Room.objects.create(
            code=r["code"].strip(), name=r["code"].strip(), building=r.get("building") or "", capacity=r["capacity"]
        )
    return found


def _check(term: AcademicTerm, data: dict, rooms: dict[str, Room]) -> None:
    problems: list[str] = []
    sessions = exam_sessions()
    start = data.get("exam_start") or term.start_date
    end = data.get("exam_end") or term.end_date
    seats = {
        _code(r["code"]): r.get("exam_seats") or r["capacity"] for r in data.get("rooms") or []
    }
    keys = [p["key"] for p in data["papers"]]
    if len(set(keys)) != len(keys):
        problems.append("Two papers have the same key.")
    in_room: dict[tuple[date, time, str], int] = defaultdict(int)
    places: dict[tuple[date, time, str], set[str]] = defaultdict(set)
    unknown: set[str] = set()
    for p in data["papers"]:
        label = "/".join(p["unit_codes"])
        if not start <= p["date"] <= end:
            problems.append(f"{label} is on {p['date']}, outside the exam period ({start} to {end}).")
        if p["date"].weekday() > 4:
            problems.append(f"{label} is on a {p['date']:%A}; exams are on weekdays.")
        if (p["start_time"], p["end_time"]) not in sessions:
            problems.append(f"{label} is at {p['start_time']:%H:%M}-{p['end_time']:%H:%M}, not one of the exam sessions.")
        mains = [s for s in p["seating"] if s["role"] == ExamSeating.Role.MAIN]
        main_staff = {s["invigilator_staff_number"].strip().upper() for s in mains}
        main_rooms = {_code(s["room_code"]) for s in mains}
        if p["seating"] and (len(main_staff) != 1 or len(main_rooms) != 1):
            problems.append(f"{label} needs exactly one main invigilator, in one room.")
        for s in p["seating"]:
            staff = s["invigilator_staff_number"].strip().upper()
            room = _code(s["room_code"])
            if not staff:
                problems.append(f"{label} has no invigilator in {room}.")
                continue
            if find_lecturer_account(staff) is None:
                unknown.add(staff)
            in_room[(p["date"], p["start_time"], room)] += s["students"]
            places[(p["date"], p["start_time"], staff)].add(room)
        examiner = (p.get("examiner_staff_number") or "").strip()
        if examiner and find_lecturer_account(examiner) is None:
            unknown.add(examiner.upper())
    for (day, start_time, room), students in in_room.items():
        limit = seats.get(room) or rooms[room].capacity
        if students > limit:
            problems.append(f"{room} seats {students} on {day} {start_time:%H:%M}; it has {limit} exam seats.")
    for (day, start_time, staff), where in places.items():
        if len(where) > 1:
            problems.append(f"{staff} invigilates in {len(where)} rooms on {day} {start_time:%H:%M}.")
    if problems:
        raise ExamPublishRefused(422, "invalid", f"{len(problems)} problems in the exam timetable.", problems=problems[:100])
    if unknown:
        raise ExamPublishRefused(
            422,
            "unknown_lecturer",
            f"SMARTTT doesn't know {len(unknown)} staff numbers: {', '.join(sorted(unknown)[:10])}.",
            staff_numbers=sorted(unknown),
        )


# -- what changed ----------------------------------------------------------------------------


def _shape(publication: ExamPublication | None) -> dict[str, dict[str, Any]]:
    if publication is None:
        return {}
    out = {}
    for paper in publication.papers.prefetch_related("seatings__room"):
        seatings = list(paper.seatings.all())
        out[paper.key] = {
            "when": (paper.date.isoformat(), paper.start_time.strftime("%H:%M")),
            "rooms": sorted({s.room.code for s in seatings}),
            "invigilators": sorted({(s.room.code, s.invigilator_staff_number, s.role) for s in seatings}),
            "seating": sorted(
                (s.room.code, json.dumps(s.class_rows, sort_keys=True), s.part, s.reg_from, s.reg_to) for s in seatings
            ),
        }
    return out


def compare(previous: ExamPublication | None, current: ExamPublication) -> dict[str, list[str]]:
    """Paper keys added, removed, moved (date or session), with rooms changed, or invigilators changed."""
    old, new = _shape(previous), _shape(current)
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "moved": sorted(k for k in set(old) & set(new) if old[k]["when"] != new[k]["when"]),
        "rooms_changed": sorted(
            k for k in set(old) & set(new) if old[k]["rooms"] != new[k]["rooms"] or old[k]["seating"] != new[k]["seating"]
        ),
        "invigilators_changed": sorted(
            k for k in set(old) & set(new) if old[k]["invigilators"] != new[k]["invigilators"]
        ),
    }


def latest_publication(term: AcademicTerm) -> ExamPublication | None:
    return ExamPublication.objects.filter(term=term).order_by("-version").first()

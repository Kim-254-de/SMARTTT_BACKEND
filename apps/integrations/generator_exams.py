"""
The Timetable Generator publishes the Directorate's approved exam timetable
here: each written paper's date, session and seating, and the departments'
practicals. Students see the papers and practicals of the units they synced
(apps/schedule/exams.py).

POST /api/v1/integrations/generator/exams/publish/   (X-API-Key = GENERATOR_API_KEY)

    {
      "term_id": "<SMARTTT term uuid>" | null,      # null: found (or created) by year and semester
      "academic_year": "2026/2027", "semester": 1,
      "term_start": "2026-09-07", "term_end": "2026-12-18",   # needed only to create the term
      "version": 2, "based_on_version": 1,
      "published_by": "Dee Director (STF/0900)",
      "papers": [{
        "key": "<Attendance paper id>",
        "codes": ["BITE 131", "COSC 130"], "title": "Computer Applications",
        "sitting": "regular" | "odel",             # ODEL and part-time students sit separate papers
        "date": "2026-11-23", "start_time": "08:30", "end_time": "10:30",
        "examiner_staff_number": "STF/0001" | null,
        "seating": [{"room_code": "STB 1", "class_row": "BSC.CS Y1S1",
                     "program_id": 4 | null, "program_code": "BSC.CS",
                     "year_of_study": 1, "study_semester": 1, "stream": "",
                     "part": 1, "parts": 1, "students": 120,
                     "invigilator_staff_number": "STF/0002" | null}]
      }],
      "practicals": [{"codes": ["COSC 200"], "title": "Data", "department": "CS",
                      "date": "2026-11-20", "start_time": "09:00", "end_time": "11:00"}]
    }

Each version is kept whole (its papers, seating and practicals); students
see the term's latest. Like the teaching publish, versions only go up:
`based_on_version` must be the term's latest exam version (409 stale_base);
re-sending a version with the same papers answers 200 with the stored
result, with different ones 409 version_taken.
"""
from __future__ import annotations

import hashlib
import json

from django.db import transaction
from rest_framework import serializers

from apps.timetable.models import AcademicTerm, ExamPaper, ExamPractical, ExamSeating, ExamTimetable

from .generator_publish import PublishRefused, _term, compact

HHMM = {"format": "%H:%M", "input_formats": ["%H:%M"]}


class _Seat(serializers.Serializer):
    room_code = serializers.CharField(max_length=30)
    class_row = serializers.CharField(max_length=120)
    program_id = serializers.IntegerField(allow_null=True, required=False)
    program_code = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    year_of_study = serializers.IntegerField(min_value=1, max_value=7, allow_null=True, required=False)
    study_semester = serializers.IntegerField(min_value=1, max_value=3, allow_null=True, required=False)
    stream = serializers.CharField(max_length=10, allow_blank=True, required=False, default="")
    part = serializers.IntegerField(min_value=1, required=False, default=1)
    parts = serializers.IntegerField(min_value=1, required=False, default=1)
    students = serializers.IntegerField(min_value=0, required=False, default=0)
    invigilator_staff_number = serializers.CharField(max_length=64, allow_null=True, allow_blank=True, required=False)


class _Paper(serializers.Serializer):
    key = serializers.CharField(max_length=120)
    codes = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=False)
    title = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    sitting = serializers.ChoiceField(choices=ExamPaper.Sitting.choices, required=False, default=ExamPaper.Sitting.REGULAR)
    date = serializers.DateField()
    start_time = serializers.TimeField(**HHMM)
    end_time = serializers.TimeField(**HHMM)
    examiner_staff_number = serializers.CharField(max_length=64, allow_null=True, allow_blank=True, required=False)
    seating = _Seat(many=True, required=False, default=list)


class _Practical(serializers.Serializer):
    codes = serializers.ListField(child=serializers.CharField(max_length=64), allow_empty=False)
    title = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    department = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    date = serializers.DateField()
    start_time = serializers.TimeField(**HHMM)
    end_time = serializers.TimeField(**HHMM)


class ExamPublishSerializer(serializers.Serializer):
    term_id = serializers.UUIDField(allow_null=True, required=False)
    academic_year = serializers.RegexField(r"^\d{4}/\d{4}$")
    semester = serializers.IntegerField(min_value=1, max_value=3)
    term_start = serializers.DateField(allow_null=True, required=False)
    term_end = serializers.DateField(allow_null=True, required=False)
    version = serializers.IntegerField(min_value=1)
    based_on_version = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    published_by = serializers.CharField(max_length=255)
    papers = _Paper(many=True, allow_empty=False)
    practicals = _Practical(many=True, required=False, default=list)


def _sha(data: dict) -> str:
    content = {"papers": data["papers"], "practicals": data["practicals"]}
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def _check(data: dict) -> None:
    problems: list[str] = []
    keys = [p["key"] for p in data["papers"]]
    if len(set(keys)) != len(keys):
        problems.append("Two papers have the same key.")
    for item in [*data["papers"], *data["practicals"]]:
        if item["end_time"] <= item["start_time"]:
            problems.append(f"{'/'.join(item['codes'])} ends before it starts.")
    if problems:
        raise PublishRefused(422, "invalid_exam_timetable", problems[0], problems=problems[:50])


def publish_exams(data: dict) -> tuple[int, dict]:
    """(HTTP status, body). Raises PublishRefused when nothing may be written."""
    sha = _sha(data)
    with transaction.atomic():
        term = _term(data)
        AcademicTerm.objects.select_for_update().filter(pk=term.pk).first()

        existing = ExamTimetable.objects.filter(term=term, version=data["version"]).first()
        if existing is not None:
            if existing.payload_sha256 == sha:
                return 200, existing.result
            raise PublishRefused(
                409, "version_taken", f"Exam version {data['version']} was already published with other papers."
            )
        latest = ExamTimetable.objects.filter(term=term).order_by("-version").first()
        latest_version = latest.version if latest else None
        if data.get("based_on_version") != latest_version or (latest_version and data["version"] <= latest_version):
            raise PublishRefused(
                409,
                "stale_base",
                f"SMARTTT has exam version {latest_version} of this term; this one was made from "
                f"{data.get('based_on_version')}. Publish from the latest version.",
                latest_version=latest_version,
            )
        _check(data)

        timetable = ExamTimetable.objects.create(
            term=term,
            version=data["version"],
            based_on_version=data.get("based_on_version"),
            published_by=data["published_by"],
            payload_sha256=sha,
        )
        seat_count = 0
        for p in data["papers"]:
            paper = ExamPaper.objects.create(
                timetable=timetable,
                key=p["key"],
                codes=list(p["codes"]),
                code_keys=[compact(c) for c in p["codes"]],
                title=p.get("title") or "",
                sitting=p.get("sitting") or ExamPaper.Sitting.REGULAR,
                date=p["date"],
                start_time=p["start_time"],
                end_time=p["end_time"],
                examiner_staff_number=(p.get("examiner_staff_number") or "").strip().upper(),
            )
            seats = [
                ExamSeating(
                    paper=paper,
                    room_code=s["room_code"].strip(),
                    class_row=s["class_row"],
                    program_id=s.get("program_id"),
                    program_code=(s.get("program_code") or "").strip(),
                    year_of_study=s.get("year_of_study"),
                    study_semester=s.get("study_semester"),
                    stream=(s.get("stream") or "").strip()[:10],
                    part=s.get("part") or 1,
                    parts=s.get("parts") or 1,
                    students=s.get("students") or 0,
                    invigilator_staff_number=(s.get("invigilator_staff_number") or "").strip().upper(),
                )
                for s in p.get("seating") or []
            ]
            ExamSeating.objects.bulk_create(seats)
            seat_count += len(seats)
        ExamPractical.objects.bulk_create(
            [
                ExamPractical(
                    timetable=timetable,
                    codes=list(pr["codes"]),
                    code_keys=[compact(c) for c in pr["codes"]],
                    title=pr.get("title") or "",
                    department=pr.get("department") or "",
                    date=pr["date"],
                    start_time=pr["start_time"],
                    end_time=pr["end_time"],
                )
                for pr in data["practicals"]
            ]
        )
        result = {
            "term_id": str(term.pk),
            "academic_year": term.academic_year,
            "semester": term.semester,
            "version": data["version"],
            "based_on_version": data.get("based_on_version"),
            "paper_count": len(data["papers"]),
            "seating_count": seat_count,
            "practical_count": len(data["practicals"]),
            "is_current": term.is_current,
        }
        timetable.result = result
        timetable.save(update_fields=["result"])
    return 201, result

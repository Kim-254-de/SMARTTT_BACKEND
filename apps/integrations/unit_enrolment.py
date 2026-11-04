"""
How many students registered each unit this term, by class row: what
Smart Attendance sizes a department's exam papers with.

POST /api/v1/integrations/attendance/unit-enrolment/   (X-API-Key = ATTENDANCE_API_KEY)

    {"codes": ["COSC 130", "MATH 241"]}

200 -> {
    "term": {"id": "<uuid>", "academic_year": "2026/2027", "semester": 1} | null,
    "units": {
        "COSC 130": {
            "code": "COSC 130", "name": "Programming", "students": 125,
            "rows": [{"program": "BSC.CS", "program_name": "BSc Computer Science",
                      "year_of_study": 1, "study_semester": 1, "stream": "",
                      "sitting": "regular", "students": 120}],
            "lecturers": [{"staff_number": "STF/0001", "name": "Jane L"}]
        }
    },
    "unknown": ["XYZ 999"]
}

A code is matched ignoring case, spaces and punctuation ("Math 241" is MATH
241). `rows` are the classes taking the unit: every class the current term's
master timetable has it under (TimetableSlot: programme, year, stream), with 0
students until someone syncs, and every class row of the students who synced
it (StudentUnit), so the timetable names the class even when nobody synced.
Duplicate Program rows (same name, different code) are one class, under one
code. A class's semester is the timetable's; on slots that don't record it, the
semester most of the programme year's active students are in; else 1.
Part-time and distance-learning students sit the ODEL paper (`sitting` "odel");
the master timetable's classes are `sitting` "regular". `unknown` lists codes
SMARTTT has no unit for; a known unit with no class has `rows` []. `lecturers`
are who teaches it on the term's timetable.

GET /api/v1/integrations/generator/rooms/   (X-API-Key = GENERATOR_API_KEY)

200 -> {"rooms": [{"code": "LH1", "name": "...", "building": "...", "capacity": 120,
                   "room_type": "lecture_hall", "status": "active",
                   "for_exams": true, "health_unit": false}]}

Every room the admin uploaded, with its capacity: the Generator seats exams in them.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from django.db.models import Count
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.courses.models import StudentUnit
from apps.programs.models import Program
from apps.programs.utils.program_key import canonical_program_key
from apps.rooms.models import Room
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

from .generator_publish import compact
from .permissions import HasAttendanceApiKey, HasGeneratorApiKey

ODEL_ENROLLMENT = {Student.EnrollmentType.PART_TIME, Student.EnrollmentType.DISTANCE_LEARNING}
MAX_CODES = 2000


class _EnrolmentQuery(serializers.Serializer):
    codes = serializers.ListField(
        child=serializers.CharField(max_length=64, allow_blank=True), allow_empty=True, max_length=MAX_CODES
    )


def _lecturer_name(slot: TimetableSlot) -> str:
    user = getattr(slot.lecturer, "user", None)
    if user is not None:
        return user.get_full_name() or user.username
    return slot.lecturer_name_text


def _program_code_names() -> dict[str, tuple[str, str]]:
    """Each Program code -> the one code and name its duplicates (same name, other codes) go under."""
    programs = list(Program.objects.only("code", "name"))
    chosen: dict[str, Program] = {}
    for p in sorted(programs, key=lambda p: p.code):
        chosen.setdefault(canonical_program_key(p.name), p)
    return {p.code: (chosen[canonical_program_key(p.name)].code, chosen[canonical_program_key(p.name)].name) for p in programs}


def _usual_semesters(one_code: dict[str, tuple[str, str]]) -> dict[tuple[str, int], int]:
    """The semester most active students of each programme year are in."""
    counts: dict[tuple[str, int], Counter] = defaultdict(Counter)
    found = (
        Student.objects.filter(is_active=True, program__isnull=False, current_semester__isnull=False)
        .values_list("program__code", "current_study_year", "current_semester")
        .annotate(n=Count("pk"))
    )
    for code, year, semester, n in found:
        if code in one_code and semester:
            counts[(one_code[code][0], int(year or 0))][int(semester)] += n
    return {key: counter.most_common(1)[0][0] for key, counter in counts.items()}


def unit_enrolment(codes: list[str]) -> dict[str, Any]:
    wanted: dict[str, str] = {}
    for code in codes:
        if compact(code):
            wanted.setdefault(compact(code), code.strip())
    term = AcademicTerm.objects.filter(is_current=True).first()

    names: dict[str, str] = {}
    for unit in Unit.objects.only("code", "name"):
        key = compact(unit.code)
        if key in wanted:
            names.setdefault(key, unit.name)

    rows: dict[str, dict[tuple, dict[str, Any]]] = defaultdict(dict)
    lecturers: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    if term is not None and wanted:
        one_code = _program_code_names()
        synced = StudentUnit.objects.filter(term=term).select_related("unit", "user__student_profile__program")
        seen: set[tuple[str, int]] = set()
        for su in synced.iterator():
            key = compact(su.unit.code)
            if key not in wanted or (key, su.user_id) in seen:
                continue
            seen.add((key, su.user_id))
            student = getattr(su.user, "student_profile", None)
            program = getattr(student, "program", None)
            code, name = one_code.get(program.code, (program.code, program.name)) if program else ("", "")
            row = (
                code,
                int(getattr(student, "current_study_year", 0) or 0),
                int(getattr(student, "current_semester", 0) or 0) or None,
                (getattr(student, "timetable_group", "") or "").strip(),
                "odel" if getattr(student, "enrollment_type", None) in ODEL_ENROLLMENT else "regular",
            )
            entry = rows[key].setdefault(
                row,
                {
                    "program": row[0],
                    "program_name": name,
                    "year_of_study": row[1],
                    "study_semester": row[2],
                    "stream": row[3],
                    "sitting": row[4],
                    "students": 0,
                },
            )
            entry["students"] += 1
        usual = _usual_semesters(one_code)
        slots = TimetableSlot.objects.filter(term=term).select_related("unit", "program", "lecturer__user")
        for slot in slots.iterator():
            key = compact(slot.unit.code) if slot.unit else ""
            if key not in wanted:
                continue
            if slot.program:
                code, name = one_code.get(slot.program.code, (slot.program.code, slot.program.name))
                semester = slot.study_semester or usual.get((code, slot.year_of_study)) or 1
                stream = (slot.stream or "").strip()
                rows[key].setdefault(
                    (code, slot.year_of_study, semester, stream, "regular"),
                    {
                        "program": code,
                        "program_name": name,
                        "year_of_study": slot.year_of_study,
                        "study_semester": semester,
                        "stream": stream,
                        "sitting": "regular",
                        "students": 0,
                    },
                )
            staff = (getattr(getattr(slot.lecturer, "user", None), "university_id", "") or "").strip().upper()
            name = _lecturer_name(slot)
            if staff or name:
                lecturers[key].setdefault(staff or name, {"staff_number": staff, "name": name})

    units: dict[str, Any] = {}
    unknown: list[str] = []
    for key, code in wanted.items():
        if key not in names and key not in rows:
            unknown.append(code)
            continue
        found = sorted(
            rows[key].values(),
            key=lambda r: (r["sitting"], r["program"], r["year_of_study"], r["study_semester"] or 0, r["stream"]),
        )
        units[code] = {
            "code": code,
            "name": names.get(key, ""),
            "students": sum(r["students"] for r in found),
            "rows": found,
            "lecturers": list(lecturers[key].values()),
        }
    return {
        "term": {"id": str(term.pk), "academic_year": term.academic_year, "semester": term.semester} if term else None,
        "units": units,
        "unknown": unknown,
    }


class AttendanceUnitEnrolmentView(APIView):
    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def post(self, request):
        query = _EnrolmentQuery(data=request.data)
        if not query.is_valid():
            return Response({"detail": "Send the unit codes as {\"codes\": [...]}.", "errors": query.errors}, status=400)
        return Response(unit_enrolment(query.validated_data["codes"]))


class GeneratorUnitEnrolmentView(APIView):
    """POST generator/unit-enrolment/: the same answer, for the health and nursing papers the Director uploads."""

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def post(self, request):
        query = _EnrolmentQuery(data=request.data)
        if not query.is_valid():
            return Response({"detail": "Send the unit codes as {\"codes\": [...]}.", "errors": query.errors}, status=400)
        return Response(unit_enrolment(query.validated_data["codes"]))


class GeneratorProgramsView(APIView):
    """GET generator/programs/: programme codes and names, to match the classes named in a moderation letter."""

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def get(self, request):
        one_code = _program_code_names()
        return Response({"programs": sorted(({"code": c, "name": n} for c, n in set(one_code.values())), key=lambda p: p["code"])})


class AttendanceProgramsView(APIView):
    """GET attendance/programs/: programme codes and names, to match the classes a department's moderation letter names."""

    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        one_code = _program_code_names()
        return Response({"programs": sorted(({"code": c, "name": n} for c, n in set(one_code.values())), key=lambda p: p["code"])})


class GeneratorRoomsView(APIView):
    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def get(self, request):
        rooms = Room.objects.order_by("building", "code")
        return Response(
            {
                "rooms": [
                    {
                        "code": r.code,
                        "name": r.name,
                        "building": r.building,
                        "capacity": r.capacity,
                        "capacity_confirmed": r.capacity_confirmed,
                        "room_type": r.room_type,
                        "status": r.status,
                        "for_exams": r.for_exams,
                        "health_unit": r.health_unit,
                    }
                    for r in rooms
                ]
            }
        )

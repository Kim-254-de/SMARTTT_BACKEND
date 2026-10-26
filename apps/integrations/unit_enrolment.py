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
241). Students are those who synced the unit in the current term
(StudentUnit). Part-time and distance-learning students sit the ODEL paper
(`sitting` "odel"). `unknown` lists codes SMARTTT has no unit for; a known unit
nobody synced has `students` 0. `lecturers` are who teaches it on the term's
timetable.

GET /api/v1/integrations/generator/rooms/   (X-API-Key = GENERATOR_API_KEY)

200 -> {"rooms": [{"code": "LH1", "name": "...", "building": "...", "capacity": 120,
                   "room_type": "lecture_hall", "status": "active"}]}

Every room the admin uploaded, with its capacity: the Generator seats exams in them.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.courses.models import StudentUnit
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
        synced = StudentUnit.objects.filter(term=term).select_related("unit", "user__student_profile__program")
        seen: set[tuple[str, int]] = set()
        for su in synced.iterator():
            key = compact(su.unit.code)
            if key not in wanted or (key, su.user_id) in seen:
                continue
            seen.add((key, su.user_id))
            student = getattr(su.user, "student_profile", None)
            program = getattr(student, "program", None)
            row = (
                program.code if program else "",
                int(getattr(student, "current_study_year", 0) or 0),
                int(getattr(student, "current_semester", 0) or 0) or None,
                (getattr(student, "timetable_group", "") or "").strip(),
                "odel" if getattr(student, "enrollment_type", None) in ODEL_ENROLLMENT else "regular",
            )
            entry = rows[key].setdefault(
                row,
                {
                    "program": row[0],
                    "program_name": program.name if program else "",
                    "year_of_study": row[1],
                    "study_semester": row[2],
                    "stream": row[3],
                    "sitting": row[4],
                    "students": 0,
                },
            )
            entry["students"] += 1
        slots = TimetableSlot.objects.filter(term=term).select_related("unit", "lecturer__user")
        for slot in slots.iterator():
            key = compact(slot.unit.code) if slot.unit else ""
            if key not in wanted:
                continue
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
                        "room_type": r.room_type,
                        "status": r.status,
                    }
                    for r in rooms
                ]
            }
        )

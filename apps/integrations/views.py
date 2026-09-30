from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasAttendanceApiKey
from .services import find_student, get_lecturer_units


class AttendanceLecturerUnitsView(APIView):
    """
    GET /api/v1/integrations/attendance/lecturer-units/?staff_number=STF/0001&name=Peter%20Kamami

    For the Smart Attendance backend only (X-API-Key). Reports one entry per
    class the lecturer teaches: a unit split into groups (GR A, GR B ...)
    appears once per group they are allocated, with only that group's students.
    Staff numbers contain "/", so they travel as a query parameter rather than
    a path segment.

    `name` is optional: used to match allocation-document slots when the staff
    number has no SMARTTT account yet. When the account exists, its own name
    is used instead.

    200 -> {
        "staff_number": "STF/0001",
        "lecturer_account": true,
        "term": {"academic_year": "2025/2026", "semester": 1} | null,
        "units": [{                       # one per class: unit + teaching group
            "code": "COSC 103 GR A",      # the class; plain "COSC 103" when not split
            "unit_code": "COSC 103", "group": "GR A" | null,
            "name": "...", "registered_students": 150,
            "students_without_group": 40, # registered for the unit, no group picked yet
            "matched_by": "account" | "name",
            "students": [{"registration_number": "EBT1/08223/23", "full_name": "..."}],
            "slots": [{"day_of_week": 1, "start_time": "08:00", "end_time": "10:00",
                       "room": "LH1", "class_group": "MAIN", "program": "..."}]
        }]
    }
    404 -> the lecturer can't be identified (no account and no name given).
    """

    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        staff_number = (request.query_params.get("staff_number") or "").strip()
        if not staff_number:
            return Response({"detail": "staff_number query param is required."}, status=400)
        name = (request.query_params.get("name") or "").strip()

        result = get_lecturer_units(staff_number, fallback_name=name)
        if result is None:
            return Response({"detail": "No lecturer with this staff number."}, status=404)

        term = result.term
        return Response({
            "staff_number": staff_number,
            "lecturer_account": result.account is not None,
            "term": {"academic_year": term.academic_year, "semester": term.semester} if term else None,
            "units": result.units,
        })


class AttendanceStudentLookupView(APIView):
    """
    GET /api/v1/integrations/attendance/students/?registration_number=EBT1/08223/23

    For the Smart Attendance backend only (X-API-Key), when a student registers
    there: confirms the registration number belongs to a SMARTTT student and
    returns the details it checks the registration against. Registration
    numbers contain "/", so they travel as a query parameter.

    200 -> {"registration_number": "EBT1/08223/23", "full_name": "...",
            "email": "..." | null, "programme": "..." | null,
            "year_of_study": 3 | null, "is_active": true}
    404 -> no student with this registration number.
    """

    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        number = (request.query_params.get("registration_number") or "").strip()
        if not number:
            return Response({"detail": "registration_number query param is required."}, status=400)
        student = find_student(number)
        if student is None:
            return Response({"detail": "No student with this registration number."}, status=404)
        return Response(student)

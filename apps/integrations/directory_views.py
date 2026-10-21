"""
Faculties and departments, for the Smart Attendance backend (X-API-Key).

SMARTTT owns the university's faculties and departments. Attendance keeps a
copy linked by SMARTTT's id (its officers, terminals and oversight hang off
it), reads them from here, and creates new ones here first: an administrator
adding a faculty, or a faculty officer adding a department, in the attendance
portals. Attendance decides who may do that; this only trusts the key.

GET  attendance/faculties/     -> {"faculties": [{"id", "name", "code"}]}
POST attendance/faculties/     {"name", "code"?} -> 201 the faculty
GET  attendance/departments/   -> {"departments": [{"id", "name", "code", "faculty_id", "status"}]}
POST attendance/departments/   {"faculty_id", "name", "code"?} -> 201 the department

A name already in use is a 409 {"code": "name_taken", "id": <existing id>}, so
the caller can link to it instead of creating a second one. A code, when not
given, is made from the name's initials ("Faculty of Science" -> "FS").
"""
from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.departments.models import Department, Faculty

from .permissions import HasAttendanceApiKey

_FILLER = {"OF", "AND", "THE", "FOR", "IN", "&"}


def _faculty_dict(f: Faculty) -> dict:
    return {"id": f.id, "name": f.name, "code": f.code}


def _department_dict(d: Department) -> dict:
    return {"id": d.id, "name": d.name, "code": d.code, "faculty_id": d.faculty_id, "status": d.status}


def _clean_name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9&]+", name.upper()) if w and w not in _FILLER]
    return "".join(w[0] for w in words)[:24] or "X"


def _free_code(wanted: str, taken: set[str]) -> str:
    """`wanted`, or `wanted2`, `wanted3` ... when it's taken."""
    code, n = wanted, 1
    while code.upper() in taken:
        n += 1
        code = f"{wanted}{n}"
    return code


def _taken(existing_id) -> Response:
    return Response({"detail": "That name is already in use.", "code": "name_taken", "id": existing_id}, status=409)


class AttendanceFacultiesView(APIView):
    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        return Response({"faculties": [_faculty_dict(f) for f in Faculty.objects.order_by("name")]})

    def post(self, request):
        name = _clean_name(request.data.get("name"))
        if not name or len(name) > 255:
            return Response({"detail": "A faculty name of up to 255 characters is required."}, status=400)
        existing = Faculty.objects.filter(name__iexact=name).first()
        if existing:
            return _taken(existing.id)
        taken = {c.upper() for c in Faculty.objects.values_list("code", flat=True)}
        code = _clean_name(request.data.get("code"))[:32] or _free_code(_initials(name), taken)
        if code.upper() in taken:
            return Response({"detail": f"The faculty code {code} is already in use.", "code": "code_taken"}, status=409)
        try:
            with transaction.atomic():
                faculty = Faculty.objects.create(name=name, code=code)
        except IntegrityError:  # a concurrent create with the same name or code
            existing = Faculty.objects.filter(name__iexact=name).first()
            return _taken(existing.id if existing else None)
        return Response(_faculty_dict(faculty), status=201)


class AttendanceDepartmentsView(APIView):
    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        departments = Department.objects.order_by("faculty__name", "name")
        return Response({"departments": [_department_dict(d) for d in departments]})

    def post(self, request):
        name = _clean_name(request.data.get("name"))
        if not name or len(name) > 255:
            return Response({"detail": "A department name of up to 255 characters is required."}, status=400)
        faculty = Faculty.objects.filter(pk=request.data.get("faculty_id")).first() if str(
            request.data.get("faculty_id") or ""
        ).isdigit() else None
        if faculty is None:
            return Response({"detail": "No such faculty in SMARTTT.", "code": "unknown_faculty"}, status=400)
        # Attendance keeps department names unique across the university, so check them all.
        existing = Department.objects.filter(name__iexact=name).first()
        if existing:
            return _taken(existing.id)
        taken = {c.upper() for c in Department.objects.filter(faculty=faculty).values_list("code", flat=True)}
        code = _clean_name(request.data.get("code"))[:32] or _free_code(_initials(name), taken)
        if code.upper() in taken:
            return Response({"detail": f"The department code {code} is already in use.", "code": "code_taken"}, status=409)
        try:
            with transaction.atomic():
                department = Department.objects.create(faculty=faculty, name=name, code=code)
        except IntegrityError:
            existing = Department.objects.filter(name__iexact=name).first()
            return _taken(existing.id if existing else None)
        return Response(_department_dict(department), status=201)

"""
Departments, for the Smart Attendance backend (X-API-Key).

SMARTTT owns the university's departments; faculties play no part. Attendance
keeps a copy linked by SMARTTT's id (its officers, terminals and oversight
hang off it), reads them from here, and creates new ones here first when an
administrator adds one in the admin console. Attendance decides who may do
that; this only trusts the key.

GET   attendance/departments/        -> {"departments": [{"id", "name", "code", "status"}]}
POST  attendance/departments/        {"name", "code"?} -> 201 the department
PATCH attendance/departments/<id>/   {"name"?, "code"?} -> 200 the department

The code is unique across the university: the Timetable Allocator and
Generator know a department by it. When not given, one is made from the
name's initials ("Department of Computer Science" -> "DCS"). A name already
in use is a 409 {"code": "name_taken", "id": <existing id>}, so the caller can
link to it instead of creating a second one; a code already in use is a 409
{"code": "code_taken"}.

PATCH is the administrator correcting a department's name or code. The same
rules apply, except that the department may keep (or recase) its own name and
code; a name or code held by another department is a 409 as above. Slots,
programs and staff hang off the department's id, so they follow the change.
"""
from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.departments.models import Department
from apps.departments.services.department_lookup import free_department_code

from .permissions import HasAttendanceApiKey

_FILLER = {"OF", "AND", "THE", "FOR", "IN", "&"}
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./&-]{0,31}$")


def _department_dict(d: Department) -> dict:
    return {"id": d.id, "name": d.name, "code": d.code, "status": d.status}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9&]+", name.upper()) if w and w not in _FILLER]
    return "".join(w[0] for w in words)[:24] or "X"


def _taken(existing_id) -> Response:
    return Response({"detail": "That name is already in use.", "code": "name_taken", "id": existing_id}, status=409)


def _code_taken(code: str) -> Response:
    return Response({"detail": f"The department code {code} is already in use.", "code": "code_taken"}, status=409)


def _bad_name() -> Response:
    return Response({"detail": "A department name of up to 255 characters is required."}, status=400)


def _bad_code() -> Response:
    return Response({"detail": "A department code is up to 32 letters, digits, spaces or . / & -.", "code": "bad_code"}, status=400)


class AttendanceDepartmentsView(APIView):
    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def get(self, request):
        return Response({"departments": [_department_dict(d) for d in Department.objects.order_by("name")]})

    def post(self, request):
        name = _clean(request.data.get("name"))
        if not name or len(name) > 255:
            return _bad_name()
        code = _clean(request.data.get("code")).upper()
        if code and not CODE.match(code):
            return _bad_code()
        existing = Department.objects.filter(name__iexact=name).first()
        if existing:
            return _taken(existing.id)
        if not code:
            code = free_department_code(_initials(name))
        elif Department.objects.filter(code__iexact=code).exists():
            return _code_taken(code)
        try:
            with transaction.atomic():
                department = Department.objects.create(name=name, code=code)
        except IntegrityError:  # a concurrent create with the same name or code
            existing = Department.objects.filter(name__iexact=name).first()
            if existing:
                return _taken(existing.id)
            return _code_taken(code)
        return Response(_department_dict(department), status=201)


class AttendanceDepartmentView(APIView):
    authentication_classes: list = []
    permission_classes = [HasAttendanceApiKey]

    def patch(self, request, pk: int):
        department = get_object_or_404(Department, pk=pk)
        name, code = department.name, department.code
        if "name" in request.data:
            name = _clean(request.data.get("name"))
            if not name or len(name) > 255:
                return _bad_name()
        if "code" in request.data:
            code = _clean(request.data.get("code")).upper()
            if not CODE.match(code):
                return _bad_code()
        others = Department.objects.exclude(pk=department.pk)
        existing = others.filter(name__iexact=name).first()
        if existing:
            return _taken(existing.id)
        if others.filter(code__iexact=code).exists():
            return _code_taken(code)
        department.name, department.code = name, code
        try:
            with transaction.atomic():
                department.save(update_fields=["name", "code"])
        except IntegrityError:  # a concurrent create or edit took the code
            return _code_taken(code)
        return Response(_department_dict(department))

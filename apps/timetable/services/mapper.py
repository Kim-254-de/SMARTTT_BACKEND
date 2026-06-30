"""
Map a normalised Excel row dict to Django model instances.
Creates missing Departments, Programs, Units, Rooms on the fly.
Never creates Lecturers automatically — lecturer field is optional.
"""
from __future__ import annotations

import re
from django.db.models import Q

from apps.core.models import Department, Faculty, Lecturer, Program, Room
from apps.timetable.models import Unit


def _get_default_faculty() -> Faculty:
    faculty, _ = Faculty.objects.get_or_create(
        code="GEN",
        defaults={"name": "General Faculty"},
    )
    return faculty


def _to_code(text: str, max_len: int = 20) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())[:max_len] or "UNK"


def resolve_department(row: dict) -> Department:
    raw = str(row.get("department") or "School of Computing").strip()
    code = _to_code(raw)
    dept = Department.objects.filter(
        Q(code__iexact=code) | Q(name__iexact=raw)
    ).first()
    if not dept:
        dept = Department.objects.create(
            code=code[:30], name=raw[:255], faculty=_get_default_faculty()
        )
    return dept


def resolve_program(row: dict, department: Department) -> Program:
    raw = str(row.get("program") or "").strip()
    if not raw:
        # Create a generic program for this department
        raw = f"{department.name} Programme"
    code = _to_code(raw, 50)
    prog = Program.objects.filter(
        Q(code__iexact=code) | Q(name__iexact=raw), department=department
    ).first()
    if not prog:
        prog = Program.objects.create(
            code=code, name=raw[:255], department=department, duration_years=4
        )
    return prog


def resolve_unit(row: dict, department: Department) -> Unit | None:
    raw_code = str(row.get("unit_code") or "").strip()
    if not raw_code:
        return None
    clean = re.sub(r"\s+", " ", raw_code).strip()
    unit = Unit.objects.filter(
        Q(code__iexact=clean) | Q(code__iexact=re.sub(r"\s", "", clean)),
        department=department,
    ).first()
    if not unit:
        # Try across all departments (unit may already exist under another dept)
        unit = Unit.objects.filter(
            Q(code__iexact=clean) | Q(code__iexact=re.sub(r"\s", "", clean))
        ).first()
    if not unit:
        name = str(row.get("unit_name") or clean)[:255]
        unit = Unit.objects.create(
            code=clean[:30], name=name, department=department, credit_hours=3
        )
    return unit


def resolve_room(row: dict) -> Room | None:
    raw = str(row.get("room") or "").strip()
    if not raw or raw.upper() == "TBA":
        return None
    code = raw[:30]
    room = Room.objects.filter(Q(code__iexact=code) | Q(code__iexact=re.sub(r"\s", "", code))).first()
    if not room:
        room = Room.objects.create(code=code, name=f"Room {code}", capacity=60)
    return room


def resolve_lecturer(row: dict, department: Department) -> Lecturer | None:
    raw = str(row.get("lecturer") or "").strip()
    if not raw:
        return None
    qs = Lecturer.objects.select_related("user").filter(
        Q(user__first_name__icontains=raw.split()[0])
        | Q(user__last_name__icontains=raw.split()[-1])
        | Q(user__university_id__iexact=raw)
    )
    if department:
        qs = qs.filter(department=department)
    return qs.first()  # returns None if not found — do not auto-create


def resolve_time(row: dict) -> tuple[str, str] | tuple[None, None]:
    st = row.get("start_time")
    et = row.get("end_time")
    if not st or not et:
        return None, None
    return str(st), str(et)

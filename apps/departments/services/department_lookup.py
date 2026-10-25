"""Finding a department by name, or creating it, now that its code is unique across the university."""
from __future__ import annotations

import re

from django.db import IntegrityError, transaction

from apps.departments.models import Department


def free_department_code(wanted: str) -> str:
    """`wanted`, or `wanted2`, `wanted3` ... when another department has it."""
    wanted = (wanted or "X")[:30]
    taken = {c.upper() for c in Department.objects.values_list("code", flat=True)}
    code, n = wanted, 1
    while code.upper() in taken:
        n += 1
        code = f"{wanted}{n}"
    return code


def department_for_name(name: str) -> Department:
    """The department with this name (any case), else a new one with a code made from the name."""
    existing = Department.objects.filter(name__iexact=name).first()
    if existing is not None:
        return existing
    wanted = re.sub(r"[^A-Z]", "", name.upper())[:20] or name.upper()[:20]
    try:
        with transaction.atomic():
            return Department.objects.create(name=name, code=free_department_code(wanted))
    except IntegrityError:  # created concurrently
        return Department.objects.get(name__iexact=name)

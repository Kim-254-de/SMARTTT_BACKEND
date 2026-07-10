"""
Sync a student's registered units into the StudentUnit table.

Called after scraping or after manual unit entry.
Credentials are never persisted — only unit codes/names are saved.
"""
from __future__ import annotations

import re
from django.db import transaction

from apps.timetable.models import AcademicTerm, Unit
from .models import StudentUnit


def _current_term() -> AcademicTerm | None:
    return AcademicTerm.objects.filter(is_current=True).first()


def _normalise_code(raw: str) -> str:
    """'COSC328' and 'COSC 328' both become 'COSC328' for matching."""
    return re.sub(r"\s+", "", raw.upper())


@transaction.atomic
def sync_units_for_student(user, unit_list: list[dict]) -> dict:
    """
    unit_list: [{"unit_code": "COSC 328", "unit_name": "MOBILE APPS..."}, ...]

    Matches each unit code to an existing Unit in the DB.
    Units that don't exist yet in the DB are skipped (not auto-created)
    — the admin must have uploaded the master timetable first.

    Returns a summary dict.
    """
    term = _current_term()
    if not term:
        raise ValueError(
            "No current academic term is set. Ask the admin to mark a term as current."
        )

    matched = []
    unmatched = []

    for entry in unit_list:
        raw_code = str(entry.get("unit_code") or "").strip()
        if not raw_code:
            continue
        clean = _normalise_code(raw_code)
        unit = Unit.objects.filter(
            code__iregex=rf"^{re.escape(raw_code)}$"
        ).first() or Unit.objects.filter(
            code__iregex=rf"^{re.escape(re.sub(r'[^A-Z0-9]', '', clean))}$"
        ).first()

        # Broader match: normalise both sides
        if not unit:
            for u in Unit.objects.filter(code__icontains=raw_code.split()[0]):
                if _normalise_code(u.code) == clean:
                    unit = u
                    break

        if unit:
            matched.append(unit)
        else:
            unmatched.append(raw_code)

    # ── Replace this term's enrollments with the fresh list ───────────────────
    existing_ids = set(
        StudentUnit.objects.filter(user=user, term=term).values_list("unit_id", flat=True)
    )
    new_ids = {u.id for u in matched}

    # Remove units no longer registered
    StudentUnit.objects.filter(user=user, term=term).exclude(unit_id__in=new_ids).delete()

    # Add newly registered units
    for unit in matched:
        StudentUnit.objects.get_or_create(user=user, unit=unit, term=term)

    return {
        "term": str(term),
        "synced": [u.code for u in matched],
        "not_found_in_master": unmatched,
        "total_synced": len(matched),
    }

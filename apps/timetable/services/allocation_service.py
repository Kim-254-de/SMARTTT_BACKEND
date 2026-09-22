"""
Applies department allocation documents to the master timetable.

Departments send their allocations one at a time. Each upload is stored as an
AllocationDocument (one per department per academic year, a re-upload replaces
that department's previous version) and lecturers are then re-resolved from
*all* of the year's stored documents together, so:

  * a later upload never blindly overwrites an earlier department's slots: the
    most specific row still wins, whichever document it came from and in
    whatever order they arrived;
  * two departments naming different lecturers for the same class at the same
    specificity is reported as a conflict and the slot keeps what it had;
  * slots a document used to set but no longer claims (row removed in a
    revision, or the document deleted) are cleared again.
"""
from __future__ import annotations

import uuid

from django.db import transaction

from apps.lecturers.models import Lecturer
from apps.timetable.models import AcademicTerm, AllocationDocument, TimetableSlot
from apps.timetable.services.allocation_matcher import SlotRef, normalise_person, plan_assignments


class LecturerDirectory:
    """Resolves allocation-document names to registered Lecturer accounts."""

    def __init__(self):
        self._lecturers = [
            (lec, set(normalise_person(lec.user.get_full_name()).split()))
            for lec in Lecturer.objects.select_related("user")
        ]
        self._cache: dict[str, Lecturer | None] = {}

    def match(self, name: str) -> Lecturer | None:
        """
        'Dr. Kwenga Ismael (FT)' -> the one lecturer whose names contain all of
        {'kwenga', 'ismael'}. Co-taught 'Luke Mwema / Kevin Tuei' links the first
        name that resolves. Returns None when no or several accounts fit, rather
        than guessing.
        """
        if name in self._cache:
            return self._cache[name]
        found = None
        for part in name.split("/"):
            tokens = set(normalise_person(part).split())
            if not tokens:
                continue
            hits = [lec for lec, names in self._lecturers if tokens <= names or (len(names) >= 2 and names <= tokens)]
            if len(hits) == 1:
                found = hits[0]
                break
        self._cache[name] = found
        return found


def same_person(lecturer: Lecturer, name: str) -> bool:
    """True when the account is one of the (possibly co-teaching) names."""
    account = set(normalise_person(lecturer.user.get_full_name()).split())
    return any(
        set(normalise_person(part).split()) & account for part in name.split("/") if part.strip()
    )


def resolve_academic_year(requested: str | None = None) -> str | None:
    if requested:
        return requested.strip()
    term = AcademicTerm.objects.filter(is_current=True).first() or AcademicTerm.objects.order_by("-start_date").first()
    return term.academic_year if term else None


def year_slots(academic_year: str):
    """
    The master timetable for the year. The master upload files off-cycle cohorts
    (e.g. "DIP.COMP SCI Y1S2") under a separate semester term of the same
    academic year, so the whole year is searched, not just the current term.
    """
    return TimetableSlot.objects.filter(term__academic_year=academic_year)


def tag_rows(rows: list[dict], document_id: str, source: str, file_name: str) -> list[dict]:
    for row in rows:
        row["document_id"] = document_id
        row["department"] = source
        row["source_file"] = file_name
    return rows


def plan_for_year(academic_year: str, documents: list[AllocationDocument], extra_rows: list[dict] | None = None,
                  replaced_sources: set[str] | None = None) -> tuple[dict, dict]:
    """Plans the year's assignments from stored documents plus not-yet-saved rows (for dry runs)."""
    replaced_sources = replaced_sources or set()
    rows: list[dict] = []
    for doc in documents:
        if doc.source not in replaced_sources:
            rows.extend(tag_rows([dict(r) for r in doc.rows], str(doc.id), doc.source, doc.file_name))
    rows.extend(extra_rows or [])

    slot_refs = [
        SlotRef(
            id=s["id"],
            unit_code=s["unit__code"] or "",
            program_code=s["program__code"] or "",
            year_of_study=s["year_of_study"],
            semester=s["term__semester"],
            class_group=s["class_group"] or "MAIN",
            stream=s["stream"] or "",
        )
        for s in year_slots(academic_year).values(
            "id", "unit__code", "program__code", "year_of_study", "term__semester", "class_group", "stream"
        )
    ]
    return plan_assignments(rows, slot_refs), {s.id: s for s in slot_refs}


def apply_plan(academic_year: str, plan: dict, directory: LecturerDirectory) -> dict:
    """
    Writes the plan: assigned slots get the winning row's lecturer; slots an
    allocation document set earlier but nothing claims any more are cleared;
    conflict slots are left exactly as they are.
    """
    assignments = plan["assignments"]
    conflict_ids = {c["slot_id"] for c in plan["conflicts"]}
    stale_ids = set(
        year_slots(academic_year)
        .filter(allocation_document__isnull=False)
        .exclude(id__in=list(assignments) + list(conflict_ids))
        .values_list("id", flat=True)
    )

    changed_slots, overridden = [], []
    slots = TimetableSlot.objects.select_related("lecturer__user").filter(id__in=list(assignments) + list(stale_ids))
    for slot in slots:
        before = (slot.lecturer_name_text, slot.lecturer_id, slot.allocation_document_id)
        if slot.id in stale_ids:
            slot.lecturer_name_text = ""
            slot.lecturer = None
            slot.allocation_document = None
        else:
            row, _scope = assignments[slot.id]
            name = row["lecturer_name"]
            lecturer = directory.match(name)
            slot.lecturer_name_text = name
            slot.allocation_document_id = uuid.UUID(row["document_id"])
            if lecturer is not None:
                slot.lecturer = lecturer
            elif slot.lecturer_id and not same_person(slot.lecturer, name):
                # An account linked by an earlier (wrong) allocation would otherwise
                # keep overriding the new name everywhere the timetable is shown.
                slot.lecturer = None
            if (
                before[2] and before[2] != slot.allocation_document_id
                and normalise_person(before[0]) != normalise_person(name)
            ):
                overridden.append((slot.id, before[0], row))
        if (slot.lecturer_name_text, slot.lecturer_id, slot.allocation_document_id) != before:
            changed_slots.append(slot)

    with transaction.atomic():
        TimetableSlot.objects.bulk_update(
            changed_slots, ["lecturer", "lecturer_name_text", "allocation_document"], batch_size=500
        )
    return {"updated": len(changed_slots), "cleared": len(stale_ids), "overridden": overridden}

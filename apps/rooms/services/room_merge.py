"""
One physical room can reach SMARTTT under several codes: "TC1" from a capacities
file, "TC 1" from a timetable upload. room_key() says they are one room, so no
new twin is made, and merging folds the existing ones together.
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.db import IntegrityError, transaction

from apps.rooms.models import Room
from apps.timetable.models import TimetableSlot

PLACEHOLDER = "TBA"


def room_key(code: str) -> str:
    """'TC 1', 'tc1', 'TC-01' -> 'TC1'. The Generator has the same rule (services/master.py)."""
    plain = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", plain)


def find_twin(code: str, exclude_pk=None) -> Room | None:
    key = room_key(code)
    rooms = Room.objects.exclude(pk=exclude_pk) if exclude_pk else Room.objects.all()
    return next((r for r in rooms if room_key(r.code) == key), None)


def _merged_values(keep: Room, others: list[Room]) -> dict:
    """What the kept room becomes. Not for exams on any twin keeps the room out: it is one room."""
    everyone = [keep, *others]
    confirmed = [r for r in others if r.capacity_confirmed]
    source = keep if keep.capacity_confirmed or not confirmed else max(confirmed, key=lambda r: r.updated_at)
    named = next((r.name for r in everyone if r.name and room_key(r.name) != room_key(r.code)), keep.name)
    return {
        "name": named,
        "building": keep.building or next((r.building for r in others if r.building), ""),
        "floor": keep.floor or next((r.floor for r in others if r.floor), ""),
        "capacity": source.capacity,
        "capacity_confirmed": source.capacity_confirmed,
        "for_exams": all(r.for_exams for r in everyone),
        "health_unit": any(r.health_unit for r in everyone),
    }


def _brief(room: Room, slots: int) -> dict:
    return {
        "id": str(room.pk), "code": room.code, "capacity": room.capacity, "capacity_confirmed": room.capacity_confirmed,
        "for_exams": room.for_exams, "health_unit": room.health_unit, "slots": slots,
    }


def duplicate_groups() -> list[dict]:
    """Each room known by more than one code: which is kept (the most used on timetables), and what it becomes."""
    groups: dict[str, list[Room]] = defaultdict(list)
    for room in Room.objects.exclude(code=PLACEHOLDER):
        groups[room_key(room.code)].append(room)
    out = []
    for key in sorted(k for k, rooms in groups.items() if len(rooms) > 1):
        rooms = groups[key]
        slots = {r.pk: TimetableSlot.objects.filter(room=r).count() for r in rooms}
        rooms.sort(key=lambda r: (-slots[r.pk], not r.capacity_confirmed, " " not in r.code, r.code))
        keep, others = rooms[0], rooms[1:]
        out.append(
            {
                "keep": _brief(keep, slots[keep.pk]),
                "merge": [_brief(r, slots[r.pk]) for r in others],
                "result": {k: v for k, v in _merged_values(keep, others).items() if k in ("capacity", "capacity_confirmed", "for_exams", "health_unit")},
            }
        )
    return out


def _repoint(old: Room, keep: Room) -> int:
    """Everything using the old room now uses the kept one. A slot it already has is dropped. Returns how many dropped."""
    dropped = 0
    for rel in Room._meta.related_objects:
        rows = rel.related_model.objects.filter(**{rel.field.name: old})
        try:
            with transaction.atomic():
                rows.update(**{rel.field.name: keep})
        except IntegrityError:
            for row in rows:
                try:
                    with transaction.atomic():
                        setattr(row, rel.field.name, keep)
                        row.save(update_fields=[rel.field.name])
                except IntegrityError:
                    row.delete()
                    dropped += 1
    return dropped


def merge_rooms(keep: Room, others: list[Room]) -> dict:
    with transaction.atomic():
        values = _merged_values(keep, others)
        dropped = sum(_repoint(old, keep) for old in others)
        for field, value in values.items():
            setattr(keep, field, value)
        keep.save()
        codes = [r.code for r in others]
        for old in others:
            old.delete()
    return {"kept": keep.code, "merged": codes, "slots_dropped": dropped}


def merge_all() -> dict:
    results = []
    for group in duplicate_groups():
        keep = Room.objects.get(pk=group["keep"]["id"])
        results.append(merge_rooms(keep, list(Room.objects.filter(pk__in=[r["id"] for r in group["merge"]]))))
    return {"groups": len(results), "rooms_removed": sum(len(r["merged"]) for r in results), "results": results}

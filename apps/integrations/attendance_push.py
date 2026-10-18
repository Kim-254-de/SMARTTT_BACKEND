"""
Tells the Smart Attendance backend when a class moves.

The attendance backend copies each lecturer's slots (day, time, room) from
GET /api/v1/integrations/attendance/lecturer-units/ and only lets a class be
activated inside its slot, fenced to its room. It re-reads that on its own
only every so often, so after a reschedule here it is told straight away:

    POST {ATTENDANCE_BASE_URL}{ATTENDANCE_TIMETABLE_CHANGES_PATH}
    X-API-Key: {ATTENDANCE_API_KEY}
    {"staff_number": "STF/0001", "unit_codes": ["COSC 103 GR A"]}

and re-syncs that lecturer (and whoever holds those classes there) at once.

Best effort, never in the way of the reschedule: sent after the transaction
commits, on a background thread, and every failure is only logged. The
attendance backend also re-syncs by itself, so a missed push only delays it.
Unset ATTENDANCE_BASE_URL (or ATTENDANCE_API_KEY) = off.
"""
from __future__ import annotations

import logging
import threading

import requests
from django.conf import settings
from django.db import transaction

from apps.integrations.services import section_code

logger = logging.getLogger(__name__)

# Generous: the attendance backend on Render's free tier can take a while to wake.
TIMEOUT_SECONDS = 30


def timetable_change_payload(slot) -> dict:
    """What the attendance backend needs to find who to re-sync for this slot."""
    lecturer = getattr(slot, "lecturer", None)
    user = getattr(lecturer, "user", None) if lecturer else None
    staff_number = (getattr(user, "university_id", "") or "").strip().upper() or None
    unit_codes = [section_code(slot.unit.code, slot.class_group)] if slot.unit else []
    return {"staff_number": staff_number, "unit_codes": unit_codes}


def _enabled() -> bool:
    return bool(getattr(settings, "ATTENDANCE_BASE_URL", "") and getattr(settings, "ATTENDANCE_API_KEY", ""))


def send_timetable_change(payload: dict) -> bool:
    """POSTs one change. True when the attendance backend accepted it; never raises."""
    url = settings.ATTENDANCE_BASE_URL.rstrip("/") + settings.ATTENDANCE_TIMETABLE_CHANGES_PATH
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"X-API-Key": settings.ATTENDANCE_API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("attendance push failed for %s: %s", payload, exc)
        return False
    if response.status_code >= 300:
        logger.warning("attendance push for %s answered %s: %s", payload, response.status_code, response.text[:200])
        return False
    return True


def notify_attendance_of_reschedule(slot) -> bool:
    """
    Queues the push for after the current transaction commits, so the
    attendance backend never reads the timetable before the change is saved.
    Returns whether a push was queued (False when the integration is off or
    the slot has neither a lecturer nor a unit to name).
    """
    if not _enabled():
        return False
    payload = timetable_change_payload(slot)
    if not payload["staff_number"] and not payload["unit_codes"]:
        return False

    def start():
        threading.Thread(target=send_timetable_change, args=(payload,), daemon=True).start()

    transaction.on_commit(start)
    return True


def change_payloads(changes: list[tuple[str | None, str]]) -> list[dict]:
    """
    (staff number or None, section code) pairs -> one payload per lecturer,
    with every class of theirs that changed. Classes with no lecturer go out
    together under staff_number None, so the attendance backend re-syncs
    whoever holds them there.
    """
    by_staff: dict[str | None, list[str]] = {}
    for staff_number, code in changes:
        number = (staff_number or "").strip().upper() or None
        codes = by_staff.setdefault(number, [])
        if code and code not in codes:
            codes.append(code)
    return [
        {"staff_number": number, "unit_codes": sorted(codes)}
        for number, codes in sorted(by_staff.items(), key=lambda item: item[0] or "")
        if number or codes
    ]


def notify_attendance_of_changes(changes: list[tuple[str | None, str]]) -> int:
    """
    Pushes a batch of changed classes - a lecturer allocated or replaced, a
    timetable version published - after the transaction commits, one POST per
    lecturer, on one background thread. Returns how many pushes were queued
    (0 when the integration is off or nothing changed).
    """
    if not _enabled():
        return 0
    payloads = change_payloads(changes)
    if not payloads:
        return 0

    def send_all():
        for payload in payloads:
            send_timetable_change(payload)

    def start():
        threading.Thread(target=send_all, daemon=True).start()

    transaction.on_commit(start)
    return len(payloads)

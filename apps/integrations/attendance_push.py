"""
Tells the Smart Attendance backend when a class moves, and (exams) the term's
exam sessions and its teaching/exams mode.

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


def queue_timetable_changes(payloads: list[dict]) -> int:
    """
    Many changes at once (a published timetable): each distinct lecturer and
    class is pushed once, after the transaction commits, on one background
    thread. Returns how many were queued.
    """
    if not _enabled():
        return 0
    unique: dict[tuple, dict] = {}
    for payload in payloads:
        if payload["staff_number"] or payload["unit_codes"]:
            unique.setdefault((payload["staff_number"], tuple(payload["unit_codes"])), payload)
    if not unique:
        return 0

    def send_all():
        for payload in unique.values():
            send_timetable_change(payload)

    transaction.on_commit(lambda: threading.Thread(target=send_all, daemon=True).start())
    return len(unique)


# -- exams ---------------------------------------------------------------------------------


def _post(path: str, payload: dict) -> bool:
    """POSTs to the attendance backend; True when accepted. Never raises."""
    url = settings.ATTENDANCE_BASE_URL.rstrip("/") + path
    try:
        response = requests.post(
            url, json=payload, headers={"X-API-Key": settings.ATTENDANCE_API_KEY}, timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        logger.warning("attendance push to %s failed: %s", path, exc)
        return False
    if response.status_code >= 300:
        logger.warning("attendance push to %s answered %s: %s", path, response.status_code, response.text[:200])
        return False
    return True


def exam_sessions_payload(publication) -> dict:
    """
    Every exam session of the term's exam timetable: one per paper per room,
    with its candidates (class rows, and the registration range when a row is
    split) and its invigilator (main or extra). The attendance backend replaces
    the term's exam sessions with these.
    """
    from apps.timetable.services.exam_service import reg_ranges

    sessions = []
    for paper in publication.papers.prefetch_related("seatings__room"):
        ranges = reg_ranges(paper)
        by_room: dict[str, list] = {}
        for seat in paper.seatings.all():
            by_room.setdefault(seat.room.code, []).append(seat)
        main = next((s.invigilator_staff_number for s in paper.seatings.all() if s.role == "main"), None)
        for room, seats in sorted(by_room.items()):
            sessions.append(
                {
                    "key": f"{paper.key}|{room}",
                    "paper_key": paper.key,
                    "unit_codes": paper.unit_codes,
                    "title": paper.title,
                    "date": paper.date.isoformat(),
                    "start_time": paper.start_time.strftime("%H:%M"),
                    "end_time": paper.end_time.strftime("%H:%M"),
                    "room": room,
                    "candidates": [
                        {
                            "class_rows": s.class_rows,
                            "reg_from": s.reg_from or ranges.get(str(s.pk), ("", ""))[0] or None,
                            "reg_to": s.reg_to or ranges.get(str(s.pk), ("", ""))[1] or None,
                            "students": s.students,
                        }
                        for s in seats
                    ],
                    "invigilator_staff_number": seats[0].invigilator_staff_number,
                    "role": seats[0].role,
                    "main_invigilator_staff_number": main,
                }
            )
    return {"term_id": str(publication.term_id), "version": publication.version, "sessions": sessions}


def push_exam_sessions(publication) -> bool:
    """Queues the term's exam sessions for after the transaction commits. False when the integration is off."""
    if not _enabled():
        return False
    payload = exam_sessions_payload(publication)
    transaction.on_commit(
        lambda: threading.Thread(
            target=_post, args=(settings.ATTENDANCE_EXAM_SESSIONS_PATH, payload), daemon=True
        ).start()
    )
    return True


def push_term_mode(term) -> bool:
    """Tells the attendance backend the term is in exam mode (teaching classes refused) or back to teaching."""
    if not _enabled():
        return False
    payload = {
        "term_id": str(term.pk),
        "mode": term.mode,
        "switched_at": term.switched_at.isoformat() if term.switched_at else None,
        "closed_at": term.exam_closed_at.isoformat() if term.exam_closed_at else None,
    }
    transaction.on_commit(
        lambda: threading.Thread(target=_post, args=(settings.ATTENDANCE_TERM_MODE_PATH, payload), daemon=True).start()
    )
    return True

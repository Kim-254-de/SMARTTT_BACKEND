"""
Switching a term from teaching to exams, as the Director schedules it in the
Timetable Generator, and closing the exam period.

    GET    /api/v1/integrations/generator/exam-mode/?term=<uuid>          the state
    POST   /api/v1/integrations/generator/exam-switch/  {term_id, at | now: true, by}   schedule, move, or switch now
    DELETE /api/v1/integrations/generator/exam-switch/?term=<uuid>&by=   cancel a scheduled switch
    POST   /api/v1/integrations/generator/exam-close/   {term_id, at | now: true, by}   schedule, move, or close now
    DELETE /api/v1/integrations/generator/exam-close/?term=<uuid>&by=    cancel a scheduled close

All with X-API-Key = GENERATOR_API_KEY. Every call is audited
(ExamModeChange: who, when, before, after). The switch is refused while the
term has no exam publication. `apply_due` (the `apply_exam_mode` command, run
every minute) flips the mode when a scheduled time passes; it is safe to run
twice. Publishing the next term's teaching timetable closes an open exam period.

In exam mode the app shows only the exam timetable: the teaching timetable is
hidden (not deleted) and Smart Attendance refuses teaching classes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.timetable.models import AcademicTerm, ExamModeChange, ExamPublication

logger = logging.getLogger(__name__)

GENERATOR = "Timetable Generator"


class ExamModeRefused(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.body = {"code": code, "detail": detail}


class ExamModeSerializer(serializers.Serializer):
    term_id = serializers.UUIDField()
    at = serializers.DateTimeField(required=False, allow_null=True)
    now = serializers.BooleanField(required=False, default=False)
    by = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("now") and not attrs.get("at"):
            raise serializers.ValidationError("Give `at` (a time) or `now: true`.")
        return attrs


def state(term: AcademicTerm) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "term_id": str(term.pk),
        "mode": term.mode,
        "exam_switch_at": iso(term.exam_switch_at),
        "switched_at": iso(term.switched_at),
        "switched_by": term.switched_by or None,
        "exam_close_at": iso(term.exam_close_at),
        "exam_closed_at": iso(term.exam_closed_at),
        "closed_by": term.closed_by or None,
    }


def _locked(term_id: Any) -> AcademicTerm:
    term = AcademicTerm.objects.select_for_update().filter(pk=term_id).first()
    if term is None:
        raise ExamModeRefused(404, "unknown_term", "SMARTTT has no such term.")
    return term


def _audit(term: AcademicTerm, action: str, by: str, before: dict) -> None:
    ExamModeChange.objects.create(term=term, action=action, by=by or GENERATOR, before=before, after=state(term))


def _future(at: datetime) -> datetime:
    if at <= timezone.now():
        raise ExamModeRefused(422, "in_the_past", "Pick a time in the future, or switch now.")
    return at


def switch(term_id: Any, at: datetime | None, now: bool, by: str) -> dict[str, Any]:
    with transaction.atomic():
        term = _locked(term_id)
        before = state(term)
        if not ExamPublication.objects.filter(term=term).exists():
            raise ExamModeRefused(409, "no_exam_publication", "This term has no exam timetable published yet.")
        if term.in_exam_mode:
            raise ExamModeRefused(409, "already_switched", "The term is already in exam mode.")
        if now:
            _switch(term, by or GENERATOR)
            action = "switch_now"
        else:
            term.exam_switch_at = _future(at)  # type: ignore[arg-type]
            # A new switch after an earlier exam period was closed starts afresh.
            term.switched_at, term.switched_by = None, ""
            term.exam_closed_at, term.closed_by = None, ""
            term.save(update_fields=["exam_switch_at", "switched_at", "switched_by", "exam_closed_at", "closed_by", "updated_at"])
            action = "schedule_switch"
        _audit(term, action, by, before)
    if now:
        _after_switch(term)
    return state(term)


def cancel_switch(term_id: Any, by: str) -> dict[str, Any]:
    with transaction.atomic():
        term = _locked(term_id)
        before = state(term)
        if term.in_exam_mode:
            raise ExamModeRefused(409, "already_switched", "The term is already in exam mode; close the exam period instead.")
        term.exam_switch_at = None
        term.save(update_fields=["exam_switch_at", "updated_at"])
        _audit(term, "cancel_switch", by, before)
    return state(term)


def close(term_id: Any, at: datetime | None, now: bool, by: str) -> dict[str, Any]:
    with transaction.atomic():
        term = _locked(term_id)
        before = state(term)
        if not term.in_exam_mode and term.exam_switch_at is None:
            raise ExamModeRefused(409, "not_switched", "Schedule or do the switch to exams before closing.")
        if now:
            if not term.in_exam_mode:
                raise ExamModeRefused(409, "not_switched", "The term isn't in exam mode yet.")
            _close(term, by or GENERATOR)
            action = "close_now"
        else:
            when = _future(at)  # type: ignore[arg-type]
            if term.exam_switch_at and when <= term.exam_switch_at and not term.in_exam_mode:
                raise ExamModeRefused(422, "before_switch", "The exam period must close after the switch.")
            term.exam_close_at = when
            term.save(update_fields=["exam_close_at", "updated_at"])
            action = "schedule_close"
        _audit(term, action, by, before)
    if now:
        _after_close(term)
    return state(term)


def cancel_close(term_id: Any, by: str) -> dict[str, Any]:
    with transaction.atomic():
        term = _locked(term_id)
        before = state(term)
        term.exam_close_at = None
        term.save(update_fields=["exam_close_at", "updated_at"])
        _audit(term, "cancel_close", by, before)
    return state(term)


def _switch(term: AcademicTerm, by: str) -> None:
    moment = timezone.now()
    term.mode = AcademicTerm.Mode.EXAMS
    term.switched_at = moment
    term.switched_by = by
    term.exam_switch_at = term.exam_switch_at or moment
    term.exam_closed_at = None
    term.closed_by = ""
    term.save(update_fields=["mode", "switched_at", "switched_by", "exam_switch_at", "exam_closed_at", "closed_by", "updated_at"])


def _close(term: AcademicTerm, by: str) -> None:
    moment = timezone.now()
    term.mode = AcademicTerm.Mode.TEACHING
    term.exam_closed_at = moment
    term.closed_by = by
    term.exam_close_at = term.exam_close_at or moment
    term.save(update_fields=["mode", "exam_closed_at", "closed_by", "exam_close_at", "updated_at"])


def _scheduled_by(term: AcademicTerm, action: str) -> str:
    last = ExamModeChange.objects.filter(term=term, action=action).order_by("-created_at").first()
    return f"{last.by} (scheduled)" if last else f"{GENERATOR} (scheduled)"


def apply_due(now: datetime | None = None) -> dict[str, list[str]]:
    """Switches and closes whose time has passed. Safe to run again: each term is flipped once."""
    now = now or timezone.now()
    done: dict[str, list[str]] = {"switched": [], "closed": []}
    due_switch = AcademicTerm.objects.filter(
        mode=AcademicTerm.Mode.TEACHING, exam_switch_at__lte=now, switched_at__isnull=True, exam_closed_at__isnull=True
    ).values_list("pk", flat=True)
    for pk in list(due_switch):
        with transaction.atomic():
            term = AcademicTerm.objects.select_for_update().get(pk=pk)
            if term.in_exam_mode or term.switched_at or not term.exam_switch_at or term.exam_switch_at > now:
                continue
            if not ExamPublication.objects.filter(term=term).exists():
                continue
            before = state(term)
            _switch(term, _scheduled_by(term, "schedule_switch"))
            _audit(term, "switched_on_schedule", term.switched_by, before)
        done["switched"].append(str(term))
        _after_switch(term)
    due_close = AcademicTerm.objects.filter(
        mode=AcademicTerm.Mode.EXAMS, exam_close_at__lte=now, exam_closed_at__isnull=True
    ).values_list("pk", flat=True)
    for pk in list(due_close):
        with transaction.atomic():
            term = AcademicTerm.objects.select_for_update().get(pk=pk)
            if not term.in_exam_mode or term.exam_closed_at or not term.exam_close_at or term.exam_close_at > now:
                continue
            before = state(term)
            _close(term, _scheduled_by(term, "schedule_close"))
            _audit(term, "closed_on_schedule", term.closed_by, before)
        done["closed"].append(str(term))
        _after_close(term)
    return done


def close_for_next_teaching(published: AcademicTerm) -> list[str]:
    """Publishing a term's teaching timetable closes any other term's open exam period."""
    closed = []
    for term in AcademicTerm.objects.filter(mode=AcademicTerm.Mode.EXAMS).exclude(pk=published.pk):
        with transaction.atomic():
            before = state(term)
            _close(term, f"{GENERATOR} (next term's teaching published)")
            _audit(term, "closed_by_next_teaching", term.closed_by, before)
        closed.append(str(term))
        _after_close(term)
    return closed


def _after_switch(term: AcademicTerm) -> None:
    """Everyone is told their exams are on, and Smart Attendance learns the mode. Never fails the switch."""
    try:
        from apps.common.services.cache_service import PersonalizationCacheService

        from .attendance_push import push_exam_sessions, push_term_mode
        from .exam_notifications import notify_switch

        PersonalizationCacheService.clear_all()
        notify_switch(term)
        push_term_mode(term)
        publication = ExamPublication.objects.filter(term=term).order_by("-version").first()
        if publication is not None:
            push_exam_sessions(publication)
    except Exception:
        logger.exception("exam mode: after switching %s", term)


def _after_close(term: AcademicTerm) -> None:
    try:
        from apps.common.services.cache_service import PersonalizationCacheService

        from .attendance_push import push_term_mode

        PersonalizationCacheService.clear_all()
        push_term_mode(term)
    except Exception:
        logger.exception("exam mode: after closing %s", term)

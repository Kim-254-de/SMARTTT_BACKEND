"""
Exam notifications, through the app's notifications (Alerts history + FCM push):

- at the switch: "Exams start on ...: see your exam timetable", to everyone
  sitting a paper and every invigilator and examiner;
- reminders the evening before (from 18:00) and 1 hour before each paper or
  duty; in exam mode they replace class reminders (send_class_reminders);
- after the switch, when a new exam version moves a paper, changes a room or
  an invigilator, only the students and invigilators affected are told.

Every delivery is recorded once (ExamReminderDelivery), so re-running is safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.fcm_service import send_to_tokens
from apps.notifications.models import FCMToken, Notification, NotificationType, StudentNotification, Target
from apps.timetable.models import AcademicTerm, ExamPaper, ExamPublication, ExamReminderDelivery
from apps.timetable.services.exam_service import latest_publication, seat_for, students_of_paper

from .services import find_lecturer_account

logger = logging.getLogger(__name__)

EVENING = time(18, 0)


def _deliver(user: User, paper_key: str, kind: str, title: str, message: str, data: dict) -> bool:
    """One notification to one person, once per (paper, kind). True when sent now."""
    try:
        with transaction.atomic():
            ExamReminderDelivery.objects.create(user=user, paper_key=paper_key, kind=kind)
            notification = Notification.objects.create(
                sent_by=None,
                title=title,
                message=message,
                notification_type=data.get("type") or NotificationType.EXAM_REMINDER,
                target=Target.ALL,
                recipients_count=1,
            )
            StudentNotification.objects.create(user=user, notification=notification)
    except IntegrityError:
        return False
    tokens = list(FCMToken.objects.filter(user=user).values_list("token", flat=True))
    if tokens:
        try:
            send_to_tokens(tokens, title, message, data={**{k: str(v) for k, v in data.items()}, "notification_id": str(notification.id)})
        except Exception:
            logger.exception("exam notification push failed for %s", user)
    return True


def _staff(paper: ExamPaper) -> dict[str, str]:
    """The paper's invigilators by staff number, with their duty (main or extra in a room)."""
    out: dict[str, str] = {}
    for s in paper.seatings.all():
        out.setdefault(s.invigilator_staff_number, f"{s.role} in {s.room.code}")
    return out


def _when(paper: ExamPaper) -> str:
    return f"{paper.date:%a %d %b} at {paper.start_time:%H:%M}"


def notify_switch(term: AcademicTerm) -> int:
    publication = latest_publication(term)
    if publication is None:
        return 0
    papers = list(publication.papers.prefetch_related("seatings__room"))
    if not papers:
        return 0
    first = min(p.date for p in papers)
    title = "Exam timetable"
    message = f"Exams start on {first:%A %d %B}: see your exam timetable."
    kind = f"switch:{term.switched_at:%Y%m%d%H%M}" if term.switched_at else "switch"
    users: dict[str, User] = {}
    for paper in papers:
        for student in students_of_paper(paper):
            users[str(student.user_id)] = student.user
        for staff in [*_staff(paper), paper.examiner_staff_number]:
            account = find_lecturer_account(staff) if staff else None
            if account is not None:
                users[str(account.pk)] = account
    data = {"type": NotificationType.EXAM_NOTICE, "screen": "exams", "term_id": str(term.pk)}
    return sum(_deliver(u, f"term:{term.pk}", kind, title, message, data) for u in users.values())


def notify_changes(term: AcademicTerm, previous: ExamPublication | None, current: ExamPublication, changes: dict) -> int:
    """After the switch: each change goes only to the students and invigilators it affects."""
    if previous is None:
        return 0
    old = {p.key: p for p in previous.papers.prefetch_related("seatings__room")}
    new = {p.key: p for p in current.papers.prefetch_related("seatings__room")}
    kind = f"change:v{current.version}"
    sent = 0
    moved = set(changes.get("moved") or [])
    rooms = set(changes.get("rooms_changed") or [])
    duties = set(changes.get("invigilators_changed") or [])
    for key in sorted(moved | rooms | duties):
        before, after = old.get(key), new.get(key)
        if before is None or after is None:
            continue
        data = {"type": NotificationType.EXAM_CHANGE, "screen": "exams", "paper_key": key}
        for student in students_of_paper(after):
            seat_before, seat_after = seat_for(student, before), seat_for(student, after)
            room_before = seat_before.room.code if seat_before else None
            room_after = seat_after.room.code if seat_after else None
            if key in moved or room_before != room_after:
                where = f" in {room_after}" if room_after else ""
                sent += _deliver(
                    student.user, key, kind, "Exam changed",
                    f"{after.codes} {after.title} is now on {_when(after)}{where}.", data,
                )
        staff_before, staff_after = _staff(before), _staff(after)
        for staff in set(staff_before) | set(staff_after):
            if key not in moved and staff_before.get(staff) == staff_after.get(staff):
                continue
            account = find_lecturer_account(staff)
            if account is None:
                continue
            duty = staff_after.get(staff)
            message = (
                f"{after.codes}: you invigilate ({duty}) on {_when(after)}."
                if duty
                else f"{after.codes} on {_when(after)}: you no longer invigilate it."
            )
            sent += _deliver(account, key, kind, "Invigilation changed", message, data)
    return sent


def send_exam_reminders(now: datetime | None = None) -> int:
    """The evening before (from 18:00) and 1 hour before each paper or duty, in exam mode."""
    now = timezone.localtime(now or timezone.now())
    term = AcademicTerm.objects.filter(is_current=True, mode=AcademicTerm.Mode.EXAMS).first()
    publication = latest_publication(term)
    if publication is None:
        return 0
    tomorrow = now.date() + timedelta(days=1)
    sent = 0
    for paper in publication.papers.prefetch_related("seatings__room").filter(date__in=[now.date(), tomorrow]):
        start = timezone.make_aware(datetime.combine(paper.date, paper.start_time), timezone.get_current_timezone())
        kinds = []
        if paper.date == tomorrow and now.time() >= EVENING:
            kinds.append(("evening", "Exam tomorrow", f"{paper.codes} {paper.title} tomorrow at {paper.start_time:%H:%M}"))
        if timedelta(0) < start - now <= timedelta(hours=1):
            kinds.append(("hour", "Exam in 1 hour", f"{paper.codes} {paper.title} at {paper.start_time:%H:%M}"))
        if not kinds:
            continue
        data = {"type": NotificationType.EXAM_REMINDER, "screen": "exams", "paper_key": paper.key}
        for student in students_of_paper(paper):
            seat = seat_for(student, paper)
            if seat is None:
                continue
            for kind, title, text in kinds:
                sent += _deliver(student.user, paper.key, kind, title, f"{text}, in {seat.room.code}.", data)
        for staff, duty in _staff(paper).items():
            account = find_lecturer_account(staff)
            if account is None:
                continue
            for kind, title, text in kinds:
                sent += _deliver(account, paper.key, kind, f"{title} (invigilation)", f"{text}: you invigilate, {duty}.", data)
    return sent

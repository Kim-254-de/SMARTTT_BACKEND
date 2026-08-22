"""Send 30-minute and 10-minute reminders for upcoming student classes."""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.notifications.fcm_service import send_to_tokens
from apps.notifications.models import (
    ClassReminderDelivery,
    FCMToken,
    Notification,
    StudentNotification,
)
from apps.timetable.models import AcademicTerm, TimetableSlot


DAY_INDEX = {
    TimetableSlot.Day.MON: 0,
    TimetableSlot.Day.TUE: 1,
    TimetableSlot.Day.WED: 2,
    TimetableSlot.Day.THU: 3,
    TimetableSlot.Day.FRI: 4,
    TimetableSlot.Day.SAT: 5,
}


class Command(BaseCommand):
    help = "Send idempotent 30-minute and 10-minute class reminders."

    def handle(self, *args, **options):
        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            self.stdout.write("No current academic term; no reminders sent.")
            return

        now = timezone.localtime()
        sent = 0
        for minutes_before in (30, 10):
            for slot, occurrence in self._upcoming_slots(term, now, minutes_before):
                student_ids = StudentUnit.objects.filter(
                    unit=slot.unit,
                    term=term,
                ).values_list("user_id", flat=True).distinct()

                for user in User.objects.filter(
                    id__in=student_ids,
                    is_active=True,
                    role=User.Role.STUDENT,
                ):
                    if self._send_reminder(slot, occurrence, user, minutes_before):
                        sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} class reminder(s)."))

    def _upcoming_slots(self, term, now, minutes_before):
        latest = now + timedelta(minutes=minutes_before + 2)
        slots = TimetableSlot.objects.select_related("unit", "room").filter(
            term=term,
            day__in=DAY_INDEX,
        )
        for slot in slots:
            target_weekday = DAY_INDEX[slot.day]
            days_ahead = (target_weekday - now.weekday()) % 7
            occurrence_date = now.date() + timedelta(days=days_ahead)
            if occurrence_date < term.start_date or occurrence_date > term.end_date:
                continue

            occurrence = timezone.make_aware(
                datetime.combine(occurrence_date, slot.start_time),
                timezone.get_current_timezone(),
            )
            remaining = (occurrence - now).total_seconds()
            target = minutes_before * 60
            if target - 60 <= remaining <= target + 60 and occurrence <= latest:
                yield slot, occurrence

    @transaction.atomic
    def _send_reminder(self, slot, occurrence, user, minutes_before):
        _, created = ClassReminderDelivery.objects.get_or_create(
            slot=slot,
            user=user,
            occurrence_date=occurrence.date(),
            minutes_before=minutes_before,
        )
        if not created:
            return False

        unit_label = f"{slot.unit.code} - {slot.unit.name}"
        room_label = f" in {slot.room.code}" if slot.room else ""
        notification = Notification.objects.create(
            sent_by=None,
            title=f"Class in {minutes_before} minutes",
            message=f"{unit_label} starts at {occurrence:%H:%M}{room_label}.",
            notification_type=Notification.Type.CLASS_REMINDER,
            target=Notification.Target.ALL,
            recipients_count=1,
        )
        StudentNotification.objects.create(user=user, notification=notification)

        tokens = list(
            FCMToken.objects.filter(user=user).values_list("token", flat=True)
        )
        if tokens:
            send_to_tokens(
                tokens,
                notification.title,
                notification.message,
                data={
                    "type": "class_reminder",
                    "notification_id": str(notification.id),
                    "slot_id": str(slot.id),
                    "minutes_before": str(minutes_before),
                },
            )
        return True

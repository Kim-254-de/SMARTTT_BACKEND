"""
Notifies students when a TimetableSlot they're enrolled in is rescheduled.

Reuses the same Notification / StudentNotification / FCM pathway that
apps.notifications.views already uses for admin/lecturer announcements,
so rescheduled classes show up in the student's Alerts screen and as a
push notification, in addition to the schedule itself updating live.
"""
from __future__ import annotations

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.notifications.fcm_service import send_to_tokens
from apps.notifications.models import (
    FCMToken,
    Notification,
    NotificationType,
    StudentNotification,
    Target,
)


def _describe_change(old_day, old_start, old_end, old_room, slot) -> tuple[str, str]:
    """Build a (title, message) pair describing what changed."""
    day_changed = old_day != slot.day_of_week
    time_changed = old_start != slot.start_time or old_end != slot.end_time
    old_room_id = getattr(old_room, "id", old_room)
    new_room_id = getattr(slot.room, "id", slot.room)
    room_changed = old_room_id != new_room_id

    unit_code = slot.unit.code if slot.unit else "Class"
    old_day_display = dict(slot.WeekDay.choices).get(old_day, old_day)
    new_day_display = slot.get_day_of_week_display()

    if room_changed and not (day_changed or time_changed):
        title = f"{unit_code}: venue changed"
        message = (
            f"{unit_code} has moved from {old_room.code if old_room else 'TBA'} "
            f"to {slot.room.code if slot.room else 'TBA'}, still {new_day_display} "
            f"{slot.start_time:%H:%M}-{slot.end_time:%H:%M}."
        )
        notif_type = NotificationType.VENUE_CHANGE
    else:
        title = f"{unit_code}: class rescheduled"
        message = (
            f"{unit_code} has been moved from {old_day_display} "
            f"{old_start:%H:%M}-{old_end:%H:%M} to {new_day_display} "
            f"{slot.start_time:%H:%M}-{slot.end_time:%H:%M}"
            f", room {slot.room.code if slot.room else 'TBA'}."
        )
        notif_type = NotificationType.TIMETABLE_CHANGE

    return title, message, notif_type


def notify_students_of_reschedule(
    slot,
    *,
    old_day,
    old_start,
    old_end,
    old_room,
    reason: str = "",
    sent_by=None,
) -> dict:
    """
    Sends a TIMETABLE_CHANGE / VENUE_CHANGE notification to every student
    enrolled in `slot.unit` for `slot.term`, and pushes to their devices.

    Returns a small summary dict — never raises on notification failure,
    since a failed notification should not roll back the reschedule itself.
    """
    if slot.unit_id is None or slot.term_id is None:
        return {"recipients": 0, "push_sent": 0, "push_attempted": 0}

    title, message, notif_type = _describe_change(old_day, old_start, old_end, old_room, slot)
    if reason:
        message = f"{message} Reason: {reason}"

    student_ids = StudentUnit.objects.filter(
        unit_id=slot.unit_id, term_id=slot.term_id
    ).values_list("user_id", flat=True)
    users = list(User.objects.filter(id__in=student_ids, is_active=True))

    if not users:
        return {"recipients": 0, "push_sent": 0, "push_attempted": 0}

    notification = Notification.objects.create(
        sent_by=sent_by,
        title=title,
        message=message,
        notification_type=notif_type,
        target=Target.ALL,
        recipients_count=len(users),
        new_venue=slot.room if notif_type == NotificationType.VENUE_CHANGE else None,
    )

    StudentNotification.objects.bulk_create(
        [StudentNotification(user=user, notification=notification) for user in users],
        ignore_conflicts=True,
    )

    user_ids = [u.id for u in users]
    tokens = list(FCMToken.objects.filter(user_id__in=user_ids).values_list("token", flat=True))
    push_sent = send_to_tokens(tokens, title, message, data={"type": notif_type}) if tokens else 0

    return {
        "notification_id": str(notification.id),
        "recipients": len(users),
        "push_attempted": len(tokens),
        "push_sent": push_sent,
    }

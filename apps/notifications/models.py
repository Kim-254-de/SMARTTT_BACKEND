import uuid
from django.db import models
from django.conf import settings


class FCMToken(models.Model):
    """
    Stores each student's Firebase Cloud Messaging device token.
    A user can have multiple tokens (multiple devices).
    Updated on every login/app open.
    """
    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fcm_tokens",
    )
    token = models.TextField(unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.ANDROID)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.email} [{self.platform}]"


class Notification(models.Model):
    """
    A notification sent by admin to students.
    Stored in DB so students can see notification history in the Alerts screen.
    """
    class Target(models.TextChoices):
        ALL = "all", "All Students"
        PROGRAM = "program", "Specific Program"
        YEAR = "year", "Specific Year of Study"

    class Type(models.TextChoices):
        TIMETABLE_CHANGE = "timetable_change", "Timetable Change"
        SYNC_REMINDER = "sync_reminder", "Sync Reminder"
        REGISTRATION_REMINDER = "registration_reminder", "Registration Reminder"
        GENERAL = "general", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_notifications",
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30, choices=Type.choices, default=Type.GENERAL
    )
    target = models.CharField(max_length=20, choices=Target.choices, default=Target.ALL)
    target_program = models.ForeignKey(
        "core.Program", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="notifications",
    )
    target_year = models.PositiveSmallIntegerField(null=True, blank=True)
    recipients_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.title} → {self.target} ({self.sent_at:%Y-%m-%d %H:%M})"


class StudentNotification(models.Model):
    """
    Junction table — tracks which notifications a student has received and read.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="my_notifications",
    )
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "notification")]
        ordering = ["-delivered_at"]

    def __str__(self):
        return f"{self.user.email} — {self.notification.title}"

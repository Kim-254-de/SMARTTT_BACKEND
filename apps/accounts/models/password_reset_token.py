import uuid
from datetime import timedelta

from apps.common.models import BaseModel
from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_token() -> str:
    return str(uuid.uuid4())


def default_expiration():
    return timezone.now() + timedelta(minutes=15)


class PasswordResetToken(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    token = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        default=generate_token,
    )
    expires_at = models.DateTimeField(default=default_expiration)
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token"], name="idx_reset_token"),
            models.Index(fields=["user", "expires_at"], name="idx_reset_user_exp"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} ({self.expires_at:%Y-%m-%d %H:%M})"

    @property
    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() < self.expires_at
from django.db import models

from apps.common.models import BaseModel


class PasswordResetToken(BaseModel):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    token = models.CharField(max_length=128, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token"], name="idx_reset_token"),
            models.Index(fields=["user", "expires_at"], name="idx_reset_user_exp"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} ({self.expires_at:%Y-%m-%d %H:%M})"

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
from django.db import models

from apps.common.models import BaseModel


class Lecturer(BaseModel):
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="lecturer_profile",
    )
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="lecturers",
    )
    rank = models.CharField(max_length=100, blank=True)
    max_weekly_teaching_hours = models.PositiveSmallIntegerField(default=12)

    class Meta:
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return f"{self.user.get_full_name()} ({self.department.code})"

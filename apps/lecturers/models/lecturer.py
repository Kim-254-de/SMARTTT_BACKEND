from django.db import models

from apps.common.models import BaseModel


class Lecturer(BaseModel):
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"

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
    # FT/PT as on the department allocation form. The Generator counts both
    # towards a department's teaching capacity per hour.
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME,
    )

    class Meta:
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return f"{self.user.get_full_name()} ({self.department.code})"

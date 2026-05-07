from django.db import models

from apps.common.models import BaseModel


class Student(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEFERRED = "deferred", "Deferred"
        GRADUATED = "graduated", "Graduated"
        DISCONTINUED = "discontinued", "Discontinued"

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="students",
    )
    admission_year = models.PositiveSmallIntegerField()
    current_year = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return f"{self.user.get_full_name()} - {self.program.code}"

from django.db import models

from apps.common.models import BaseModel


class Program(BaseModel):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=30, unique=True)
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="programs",
    )
    duration_years = models.PositiveSmallIntegerField(default=4)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

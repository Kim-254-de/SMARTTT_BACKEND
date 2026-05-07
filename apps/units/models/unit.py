from django.db import models

from apps.common.models import BaseModel


class Unit(BaseModel):
    title = models.CharField(max_length=255)
    code = models.CharField(max_length=30, unique=True)
    credit_hours = models.PositiveSmallIntegerField(default=3)
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="units",
    )

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"

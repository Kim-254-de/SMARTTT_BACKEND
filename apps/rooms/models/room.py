from django.db import models

from apps.common.models import BaseModel


class Room(BaseModel):
    class Type(models.TextChoices):
        LECTURE_HALL = "lecture_hall", "Lecture Hall"
        LAB = "lab", "Lab"
        SEMINAR = "seminar", "Seminar"

    code = models.CharField(max_length=30, unique=True)
    building = models.CharField(max_length=255)
    floor = models.CharField(max_length=20, blank=True)
    capacity = models.PositiveIntegerField()
    room_type = models.CharField(max_length=30, choices=Type.choices, default=Type.LECTURE_HALL)

    class Meta:
        ordering = ["building", "code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.capacity})"

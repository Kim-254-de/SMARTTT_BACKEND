from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class Room(BaseModel):
    class Type(models.TextChoices):
        LECTURE_HALL = "lecture_hall", _("Lecture Hall")
        LAB = "lab", _("Lab")
        SEMINAR = "seminar", _("Seminar")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        MAINTENANCE = "maintenance", _("Under Maintenance")
        CLOSED = "closed", _("Closed")
        UNAVAILABLE = "unavailable", _("Unavailable")

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=255)
    building = models.CharField(max_length=255)
    floor = models.CharField(max_length=20, blank=True)
    capacity = models.PositiveIntegerField()
    # False while `capacity` is only a placeholder (e.g. rooms auto-created by a
    # timetable upload). Set once an admin records the real figure.
    capacity_confirmed = models.BooleanField(default=False)
    room_type = models.CharField(max_length=30, choices=Type.choices, default=Type.LECTURE_HALL)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    for_exams = models.BooleanField(
        default=True,
        help_text="Whether exams can be sat here. The Director can overrule this in the Timetable Generator.",
    )
    health_unit = models.BooleanField(
        default=False,
        help_text="In the health unit: health and nursing papers sit only in these rooms.",
    )
    description = models.TextField(blank=True)
    facilities = models.TextField(blank=True)

    class Meta:
        ordering = ["building", "code"]

    def __str__(self) -> str:
        return f"{self.name or self.code} ({self.capacity})"

    def is_available(self) -> bool:
        """Check if room is currently active and available."""
        return self.status == self.Status.ACTIVE

    def get_type_display_short(self) -> str:
        """Get shortened type label."""
        mapping = {
            self.Type.LECTURE_HALL: "LH",
            self.Type.LAB: "Lab",
            self.Type.SEMINAR: "Sem",
        }
        return mapping.get(self.room_type, self.room_type)

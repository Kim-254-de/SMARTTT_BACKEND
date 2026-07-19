import uuid
from django.db import models
from django.conf import settings


class Faculty(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=30, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Faculties"

    def __str__(self):
        return f"{self.name} ({self.code})"


class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name="departments")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=30)

    class Meta:
        unique_together = [("faculty", "code")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Program(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="programs")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    duration_years = models.PositiveSmallIntegerField(default=4)

    class Meta:
        unique_together = [("department", "code")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class RoomType(models.TextChoices):
        LECTURE_HALL = "lecture_hall", "Lecture Hall"
        LAB = "lab", "Lab"
        SEMINAR = "seminar", "Seminar"

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=255, blank=True)
    building = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(default=60)
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.LECTURE_HALL)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} (cap:{self.capacity})"


class Lecturer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lecturer_profile",
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="lecturers")
    title = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["user__last_name"]

    def __str__(self):
        return f"{self.title} {self.user.get_full_name()}".strip()
        
        
class ValidStaffID(models.Model):
    """
    Pre-loaded list of valid staff IDs uploaded by admin via CSV.
    Lecturer registration checks against this list.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff_id = models.CharField(max_length=50, unique=True)
    name_hint = models.CharField(max_length=255, blank=True)  # optional name from CSV
    is_claimed = models.BooleanField(default=False)  # True once a lecturer registers
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff_id"]

    def __str__(self):
        return f"{self.staff_id} ({'claimed' if self.is_claimed else 'unclaimed'})"

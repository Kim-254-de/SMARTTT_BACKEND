import uuid
from django.db import models


class AcademicTerm(models.Model):
    """A semester/term in the academic calendar."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.CharField(max_length=20)   # e.g. "2025/2026"
    semester = models.PositiveSmallIntegerField()      # 1 or 2
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = [("academic_year", "semester")]
        ordering = ["-academic_year", "-semester"]

    def __str__(self):
        return f"{self.academic_year} Sem {self.semester}"


class Unit(models.Model):
    """A course unit offered by a department."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30)       # e.g. "COSC 328"
    name = models.CharField(max_length=255)
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, related_name="units"
    )
    credit_hours = models.PositiveSmallIntegerField(default=3)

    class Meta:
        unique_together = [("department", "code")]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class TimetableSlot(models.Model):
    """
    One row in the master timetable.
    Represents a scheduled class: what unit, when, where, taught by whom,
    for which program/year.
    Admin populates this by uploading an Excel file.
    """

    class Day(models.TextChoices):
        MON = "MON", "Monday"
        TUE = "TUE", "Tuesday"
        WED = "WED", "Wednesday"
        THU = "THU", "Thursday"
        FRI = "FRI", "Friday"
        SAT = "SAT", "Saturday"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name="slots")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="slots")
    program = models.ForeignKey(
        "core.Program", on_delete=models.PROTECT, related_name="timetable_slots"
    )
    year_of_study = models.PositiveSmallIntegerField(default=1)
    lecturer = models.ForeignKey(
        "core.Lecturer", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="teaching_slots",
    )
    room = models.ForeignKey(
        "core.Room", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="scheduled_slots",
    )
    day = models.CharField(max_length=3, choices=Day.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["term", "day", "start_time"]
        indexes = [
            models.Index(fields=["term", "unit"]),
            models.Index(fields=["term", "program", "year_of_study"]),
            models.Index(fields=["day", "start_time"]),
        ]

    def __str__(self):
        return f"{self.unit.code} {self.day} {self.start_time:%H:%M}"


class TimetableUpload(models.Model):
    """Audit record for each Excel file uploaded by admin."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        PARTIAL = "partial", "Partial — some rows failed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="timetable_uploads"
    )
    uploaded_file = models.FileField(upload_to="timetable_uploads/%Y/%m/")
    term = models.ForeignKey(
        AcademicTerm, on_delete=models.PROTECT,
        null=True, blank=True, related_name="uploads",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    rows_received = models.PositiveIntegerField(default=0)
    rows_saved = models.PositiveIntegerField(default=0)
    rows_failed = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"Upload by {self.uploaded_by} at {self.uploaded_at:%Y-%m-%d %H:%M} ({self.status})"

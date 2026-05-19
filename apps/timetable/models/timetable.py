from django.db import models

from apps.common.models import BaseModel


class AcademicTerm(BaseModel):
    academic_year = models.CharField(max_length=20)
    semester = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = ("academic_year", "semester")
        ordering = ["-academic_year", "-semester"]

    def __str__(self) -> str:
        return f"{self.academic_year} S{self.semester}"


class TimetableUploadBatch(BaseModel):
    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        VALIDATED = "validated", "Validated"
        FAILED = "failed", "Failed"
        PROCESSED = "processed", "Processed"

    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="timetable_upload_batches",
    )
    source_file = models.FileField(upload_to="timetable_uploads/%Y/%m/%d")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    rows_received = models.PositiveIntegerField(default=0)
    rows_saved = models.PositiveIntegerField(default=0)
    validation_errors = models.JSONField(default=list, blank=True)


class TimetableSlot(BaseModel):
    class WeekDay(models.TextChoices):
        MONDAY = "mon", "Monday"
        TUESDAY = "tue", "Tuesday"
        WEDNESDAY = "wed", "Wednesday"
        THURSDAY = "thu", "Thursday"
        FRIDAY = "fri", "Friday"
        SATURDAY = "sat", "Saturday"

    term = models.ForeignKey(
        "timetable.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="slots",
    )
    curriculum_unit = models.ForeignKey(
        "curriculum.CurriculumUnit",
        on_delete=models.PROTECT,
        related_name="timetable_slots",
    )
    lecturer = models.ForeignKey(
        "lecturers.Lecturer",
        on_delete=models.PROTECT,
        related_name="teaching_slots",
    )
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.PROTECT,
        related_name="scheduled_slots",
    )
    day_of_week = models.CharField(max_length=10, choices=WeekDay.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    class_group = models.CharField(max_length=50, default="MAIN")
    upload_batch = models.ForeignKey(
        "timetable.TimetableUploadBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slots",
    )

    class Meta:
        ordering = ["term", "day_of_week", "start_time"]

    def __str__(self) -> str:
        return f"{self.curriculum_unit} {self.day_of_week} {self.start_time}"


class TimetableConflict(BaseModel):
    class Type(models.TextChoices):
        ROOM = "room", "Room Conflict"
        LECTURER = "lecturer", "Lecturer Conflict"
        PROGRAM = "program", "Program Conflict"

    conflict_type = models.CharField(max_length=20, choices=Type.choices)
    term = models.ForeignKey("timetable.AcademicTerm", on_delete=models.PROTECT)
    slot_a = models.ForeignKey(
        "timetable.TimetableSlot",
        on_delete=models.CASCADE,
        related_name="conflicts_as_primary",
    )
    slot_b = models.ForeignKey(
        "timetable.TimetableSlot",
        on_delete=models.CASCADE,
        related_name="conflicts_as_secondary",
    )
    details = models.JSONField(default=dict, blank=True)

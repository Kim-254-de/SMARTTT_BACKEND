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
    rows_failed = models.PositiveIntegerField(default=0)
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
    unit = models.ForeignKey(
        "units.Unit",
        on_delete=models.PROTECT,
        related_name="timetable_slots",
        null=True,
        blank=True,
    )
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="timetable_slots",
        null=True,
        blank=True,
    )
    year_of_study = models.PositiveSmallIntegerField(default=1)
    lecturer = models.ForeignKey(
        "lecturers.Lecturer",
        on_delete=models.PROTECT,
        related_name="teaching_slots",
        null=True,
        blank=True,
    )
    lecturer_name_text = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Fallback display name for the lecturer when no linked "
                  "Lecturer account exists yet (e.g. parsed from a document "
                  "but not yet matched to a registered account).",
    )
    allocation_document = models.ForeignKey(
        "timetable.AllocationDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_slots",
        help_text="Department allocation document whose row currently sets this "
                  "slot's lecturer; blank when set by hand or not yet allocated.",
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
    stream = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Numbered sub-stream of this program+year+semester cohort as "
                  "printed on the master timetable, e.g. the '1' in "
                  "'BED.MATH/CHEM Y3S1(1)'. Blank when the cohort has only one "
                  "stream. Unlike class_group (which varies per shared unit "
                  "pool - e.g. GR_J for one pool, GR_C for another, within the "
                  "same stream), this identifies the single physical row/class "
                  "the slot was printed under, so a student's whole stream can "
                  "be selected as one consistent set regardless of how many "
                  "different class_group letters its units individually use.",
    )
    upload_batch = models.ForeignKey(
        "timetable.TimetableUploadBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slots",
    )
    generator_key = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_index=True,
        help_text="Set on slots published by the Timetable Generator: its stable "
                  "session key plus the class row ('COSC103-GRA-1|BSCCOMPSCIY1S1'), "
                  "so a later version updates the same slot (keeping its lecturer) "
                  "instead of replacing it. Blank for uploaded slots.",
    )

    class Meta:
        ordering = ["term", "day_of_week", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "term", "program", "unit", "year_of_study", "day_of_week",
                    "start_time", "end_time", "room", "class_group", "stream",
                ],
                name="unique_timetable_slot",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.unit.code} {self.day_of_week} {self.start_time}"


class TimetablePublication(BaseModel):
    """
    A version of a term's master timetable published by the Timetable
    Generator (apps/integrations/generator_publish.py). Versions only go up;
    re-sending one is answered with the stored result.
    """

    term = models.ForeignKey("timetable.AcademicTerm", on_delete=models.CASCADE, related_name="publications")
    version = models.PositiveIntegerField()
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    published_by = models.CharField(max_length=255)
    payload_sha256 = models.CharField(max_length=64)
    session_count = models.PositiveIntegerField(default=0)
    slot_count = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict)

    class Meta:
        unique_together = ("term", "version")
        ordering = ["term", "-version"]

    def __str__(self) -> str:
        return f"{self.term} v{self.version}"


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

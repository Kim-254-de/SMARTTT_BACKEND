"""
The exam timetable, published by the Timetable Generator
(apps/integrations/exam_publish.py).

A term's latest ExamPublication is its exam timetable: each ExamPaper (one
or more unit codes sat together) on a real date and session, and its
ExamSeating: which class rows (or which registration-number range of one)
sit in which room, with the room's invigilator (main or extra). Every
student is told one room. Practicals are on dates their departments set and
are only shown.
"""

from django.db import models

from apps.common.models import BaseModel


class ExamPublication(BaseModel):
    """A version of a term's exam timetable. Versions only go up; re-sending one returns the stored result."""

    term = models.ForeignKey("timetable.AcademicTerm", on_delete=models.CASCADE, related_name="exam_publications")
    version = models.PositiveIntegerField()
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    published_by = models.CharField(max_length=255)
    payload_sha256 = models.CharField(max_length=64)
    exam_start = models.DateField(null=True, blank=True)
    exam_end = models.DateField(null=True, blank=True)
    result = models.JSONField(default=dict)

    class Meta:
        unique_together = ("term", "version")
        ordering = ["term", "-version"]

    def __str__(self) -> str:
        return f"{self.term} exams v{self.version}"


class ExamPaper(BaseModel):
    """
    One paper: its unit codes ("BITE 131", "COSC 130"), date and session, and examiner.

    ODEL and part-time students sit separate papers (`sitting` "odel"), so a
    unit can have two papers in one version, one per sitting.
    """

    class Sitting(models.TextChoices):
        REGULAR = "regular", "Regular"
        ODEL = "odel", "ODEL / part-time"

    publication = models.ForeignKey(ExamPublication, on_delete=models.CASCADE, related_name="papers")
    key = models.CharField(max_length=120, help_text="The Generator's stable id for the paper.")
    unit_codes = models.JSONField(default=list)
    title = models.CharField(max_length=255)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    examiner_staff_number = models.CharField(max_length=64, blank=True, default="")
    sitting = models.CharField(max_length=10, choices=Sitting.choices, default=Sitting.REGULAR)

    class Meta:
        unique_together = ("publication", "key")
        ordering = ["date", "start_time", "key"]

    @property
    def codes(self) -> str:
        return "/".join(self.unit_codes)

    def __str__(self) -> str:
        return f"{self.codes} {self.date} {self.start_time:%H:%M}"


class ExamSeating(BaseModel):
    """
    Where a class row (all of it, or part `part` of `parts` / a registration
    range) sits a paper, and who invigilates that room: the paper's main
    invigilator in its main room, else the room's extra one.
    """

    class Role(models.TextChoices):
        MAIN = "main", "Main"
        EXTRA = "extra", "Extra"

    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name="seatings")
    room = models.ForeignKey("rooms.Room", on_delete=models.PROTECT, related_name="exam_seatings")
    # [{program, year_of_study, study_semester, stream}]
    class_rows = models.JSONField(default=list)
    reg_from = models.CharField(max_length=50, blank=True, default="")
    reg_to = models.CharField(max_length=50, blank=True, default="")
    part = models.PositiveSmallIntegerField(default=1)
    parts = models.PositiveSmallIntegerField(default=1)
    students = models.PositiveIntegerField()
    invigilator_staff_number = models.CharField(max_length=64)
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        ordering = ["paper", "room__code", "part"]


class Practical(BaseModel):
    """A practical on the date its department set; shown, never moved."""

    publication = models.ForeignKey(ExamPublication, on_delete=models.CASCADE, related_name="practicals")
    unit_codes = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True, default="")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["date", "start_time"]


class ExamModeChange(BaseModel):
    """Every call that schedules, moves, cancels or does the switch to exams or the close (audit)."""

    term = models.ForeignKey("timetable.AcademicTerm", on_delete=models.CASCADE, related_name="exam_mode_changes")
    action = models.CharField(max_length=30)
    by = models.CharField(max_length=255)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]


class ExamReminderDelivery(BaseModel):
    """Idempotency record for an exam reminder or notice (one per user, paper and kind)."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="exam_reminders")
    paper_key = models.CharField(max_length=160)
    kind = models.CharField(max_length=30)  # evening | hour | switch | change:<hash>

    class Meta:
        unique_together = ("user", "paper_key", "kind")

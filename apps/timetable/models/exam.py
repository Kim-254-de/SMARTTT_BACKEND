from django.db import models

from apps.common.models import BaseModel


class ExamTimetable(BaseModel):
    """
    A version of a term's exam timetable published by the Timetable Generator
    (apps/integrations/generator_exams.py). Versions only go up; re-sending one
    is answered with the stored result. Students see the term's latest version.
    """

    term = models.ForeignKey("timetable.AcademicTerm", on_delete=models.CASCADE, related_name="exam_timetables")
    version = models.PositiveIntegerField()
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    published_by = models.CharField(max_length=255)
    payload_sha256 = models.CharField(max_length=64)
    result = models.JSONField(default=dict)

    class Meta:
        unique_together = ("term", "version")
        ordering = ["term", "-version"]

    def __str__(self) -> str:
        return f"{self.term} exams v{self.version}"


class ExamPaper(BaseModel):
    """
    One written paper: all the units it carries ("BITE 131/COSC 130") sit it
    together, on one date and session. `code_keys` are the codes compacted
    ("COSC130"), which is how a student's synced units are matched to it.
    ODEL and part-time students sit separate papers (`sitting` "odel"), so a
    unit can have two papers: a student sees the one their class sits.
    """

    class Sitting(models.TextChoices):
        REGULAR = "regular", "Regular"
        ODEL = "odel", "ODEL / part-time"

    timetable = models.ForeignKey(ExamTimetable, on_delete=models.CASCADE, related_name="papers")
    key = models.CharField(max_length=120)
    codes = models.JSONField(default=list)
    code_keys = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True)
    sitting = models.CharField(max_length=10, choices=Sitting.choices, default=Sitting.REGULAR)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    examiner_staff_number = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["date", "start_time", "key"]

    def __str__(self) -> str:
        return f"{'/'.join(self.codes)} {self.date} {self.start_time:%H:%M}"


class ExamSeating(BaseModel):
    """
    Where a class row (or one part of a class row bigger than any room) sits a
    paper. The programme, year and stream say which students that is; seating
    sent before they were included carries only `class_row` (its label).
    """

    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name="seating")
    room_code = models.CharField(max_length=30)
    class_row = models.CharField(max_length=120)
    program_id = models.IntegerField(null=True, blank=True)
    program_code = models.CharField(max_length=64, blank=True)
    year_of_study = models.PositiveSmallIntegerField(null=True, blank=True)
    study_semester = models.PositiveSmallIntegerField(null=True, blank=True)
    stream = models.CharField(max_length=10, blank=True)
    part = models.PositiveSmallIntegerField(default=1)
    parts = models.PositiveSmallIntegerField(default=1)
    students = models.PositiveIntegerField(default=0)
    invigilator_staff_number = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["room_code", "class_row", "part"]


class ExamPractical(BaseModel):
    """A practical exam on a date its department set; shown beside the papers."""

    timetable = models.ForeignKey(ExamTimetable, on_delete=models.CASCADE, related_name="practicals")
    codes = models.JSONField(default=list)
    code_keys = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True)
    department = models.CharField(max_length=64, blank=True)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["date", "start_time"]

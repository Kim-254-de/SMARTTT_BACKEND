from django.db import models

from apps.common.models import BaseModel


class StudentEnrollment(BaseModel):
    class Status(models.TextChoices):
        ENROLLED = "enrolled", "Enrolled"
        DROPPED = "dropped", "Dropped"
        COMPLETED = "completed", "Completed"

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="unit_enrollments",
    )
    curriculum_unit = models.ForeignKey(
        "curriculum.CurriculumUnit",
        on_delete=models.PROTECT,
        related_name="student_enrollments",
    )
    term = models.ForeignKey(
        "timetable.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="unit_enrollments",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ENROLLED)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ("student", "curriculum_unit", "term")

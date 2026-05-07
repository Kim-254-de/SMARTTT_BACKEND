from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel


class Curriculum(BaseModel):
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="curricula",
    )
    version_name = models.CharField(max_length=50)
    effective_academic_year = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("program", "version_name")
        ordering = ["program__code", "version_name"]

    def __str__(self) -> str:
        return f"{self.program.code} {self.version_name}"


class CurriculumUnit(BaseModel):
    class Semester(models.IntegerChoices):
        ONE = 1, "Semester 1"
        TWO = 2, "Semester 2"
        THREE = 3, "Semester 3"

    curriculum = models.ForeignKey(
        "curriculum.Curriculum",
        on_delete=models.CASCADE,
        related_name="curriculum_units",
    )
    unit = models.ForeignKey(
        "units.Unit",
        on_delete=models.PROTECT,
        related_name="curriculum_mappings",
    )
    year_of_study = models.PositiveSmallIntegerField()
    semester = models.PositiveSmallIntegerField(choices=Semester.choices)
    is_core = models.BooleanField(default=True)

    class Meta:
        unique_together = ("curriculum", "unit")
        ordering = ["curriculum", "year_of_study", "semester", "unit__code"]

    def clean(self) -> None:
        if self.year_of_study > self.curriculum.program.duration_years:
            raise ValidationError("year_of_study exceeds the program duration.")

    def __str__(self) -> str:
        return f"{self.curriculum} / Y{self.year_of_study} S{self.semester} / {self.unit.code}"

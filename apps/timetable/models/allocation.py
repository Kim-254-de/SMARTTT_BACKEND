from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AllocationDocument(BaseModel):
    """
    One department's course-allocation document for an academic year.

    Departments send their allocations separately, so every upload is kept and
    lecturers are re-resolved across all of the year's documents each time one
    arrives. Uploading again for the same department (``source``) replaces that
    department's previous version instead of stacking on top of it.
    """

    source = models.CharField(
        max_length=150,
        help_text="Department the allocation came from, e.g. 'DEPARTMENT OF EDUCATION'.",
    )
    academic_year = models.CharField(max_length=20)
    file_name = models.CharField(max_length=255)
    rows = models.JSONField(default=list, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocation_documents",
    )

    class Meta:
        ordering = ["academic_year", "source"]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "source"], name="unique_allocation_source_per_year"),
        ]

    def __str__(self) -> str:
        return f"{self.source} ({self.academic_year})"

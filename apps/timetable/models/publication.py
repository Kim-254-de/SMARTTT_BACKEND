from django.db import models

from apps.common.models import BaseModel


class TimetablePublication(BaseModel):
    """
    One numbered version of a term's timetable, published by the Timetable
    Generator once the Director of Examinations and Timetabling approves it.

    Versions count up per term from 1. A publish names the version it was built
    on (`based_on_version`), and is refused unless that is still the term's
    latest, so two drafts can never both be published over each other.
    Re-sending a version with the same content (`sha256`) returns the stored
    result instead of publishing twice.
    """

    term = models.ForeignKey(
        "timetable.AcademicTerm",
        on_delete=models.PROTECT,
        related_name="publications",
    )
    version = models.PositiveIntegerField()
    based_on_version = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64)
    published_by = models.CharField(
        max_length=255,
        help_text="Who approved it in the Generator (their SMARTTT account id and name).",
    )
    session_count = models.PositiveIntegerField(default=0)
    slot_count = models.PositiveIntegerField(default=0)
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Session keys added, moved, removed and unchanged by this version.",
    )

    class Meta:
        ordering = ["term", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["term", "version"], name="unique_publication_version_per_term"),
        ]

    def __str__(self) -> str:
        return f"{self.term} v{self.version}"

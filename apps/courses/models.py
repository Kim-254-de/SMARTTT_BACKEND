import uuid
from django.db import models


class StudentUnit(models.Model):
    """
    Records which units a student is registered for in a given term.
    Populated by the portal scraper or manual entry — never from portal passwords
    stored in the DB (credentials are used once then discarded).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="student_units"
    )
    unit = models.ForeignKey(
        "timetable.Unit", on_delete=models.CASCADE, related_name="student_registrations"
    )
    term = models.ForeignKey(
        "timetable.AcademicTerm", on_delete=models.PROTECT, related_name="student_units"
    )
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "unit", "term")]
        ordering = ["unit__code"]

    def __str__(self):
        return f"{self.user.university_id} — {self.unit.code} ({self.term})"

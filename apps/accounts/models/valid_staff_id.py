import uuid

from django.db import models


class ValidStaffID(models.Model):
    """
    Pre-loaded list of valid staff IDs uploaded by admin via CSV.
    Lecturer registration checks against this list.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff_id = models.CharField(max_length=50, unique=True)
    name_hint = models.CharField(max_length=255, blank=True)  # optional name from CSV
    is_claimed = models.BooleanField(default=False)  # True once a lecturer registers
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff_id"]

    def __str__(self):
        return f"{self.staff_id} ({'claimed' if self.is_claimed else 'unclaimed'})"

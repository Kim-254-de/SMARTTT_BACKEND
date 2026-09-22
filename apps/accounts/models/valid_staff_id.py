import uuid

from django.conf import settings
from django.db import models


class StaffIDUpload(models.Model):
    """One CSV of staff IDs uploaded by an admin, so an upload can be reviewed or undone."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file_name = models.CharField(max_length=255)
    ids_created = models.PositiveIntegerField(default=0)
    ids_skipped = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_id_uploads",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.file_name} ({self.ids_created} IDs)"


class ValidStaffID(models.Model):
    """
    Pre-loaded list of valid staff IDs uploaded by admin via CSV.
    Lecturer registration checks against this list.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff_id = models.CharField(max_length=50, unique=True)
    name_hint = models.CharField(max_length=255, blank=True)  # optional name from CSV
    is_claimed = models.BooleanField(default=False)  # True once a lecturer registers
    upload = models.ForeignKey(
        StaffIDUpload,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_ids",
    )  # CSV that added this ID; blank for IDs loaded before uploads were tracked
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff_id"]

    def __str__(self):
        return f"{self.staff_id} ({'claimed' if self.is_claimed else 'unclaimed'})"

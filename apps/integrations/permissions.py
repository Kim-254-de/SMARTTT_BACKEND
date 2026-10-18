import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class _SharedKeyPermission(BasePermission):
    """
    Lets one partner system in with its shared key in `X-API-Key`.

    Each system has its own key (and setting), so a key only opens that
    system's endpoints: the Allocator's key can't publish a timetable and the
    attendance key can't allocate lecturers.

    Fails closed: when the setting is unset, every request is refused, so a
    missing env var can never leave the endpoints open.
    """

    setting_name = ""
    message = "A valid X-API-Key header is required."

    def has_permission(self, request, view) -> bool:
        expected = getattr(settings, self.setting_name, "") or ""
        provided = request.headers.get("X-API-Key", "") or ""
        if not expected or not provided:
            return False
        return hmac.compare_digest(provided.encode(), expected.encode())


class HasAttendanceApiKey(_SharedKeyPermission):
    """The Smart Attendance backend (ATTENDANCE_API_KEY)."""

    setting_name = "ATTENDANCE_API_KEY"


class HasAllocatorApiKey(_SharedKeyPermission):
    """The Timetable Allocator, the departments' lecturer allocation system (ALLOCATOR_API_KEY)."""

    setting_name = "ALLOCATOR_API_KEY"


class HasGeneratorApiKey(_SharedKeyPermission):
    """The Timetable Generator, the Director of Examinations' solver (GENERATOR_API_KEY)."""

    setting_name = "GENERATOR_API_KEY"

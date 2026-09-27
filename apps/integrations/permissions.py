import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasAttendanceApiKey(BasePermission):
    """
    Lets the Smart Attendance backend in with the shared key in `X-API-Key`.

    Fails closed: when ATTENDANCE_API_KEY is unset, every request is refused,
    so a missing env var can never leave the endpoint open.
    """

    message = "A valid X-API-Key header is required."

    def has_permission(self, request, view) -> bool:
        expected = getattr(settings, "ATTENDANCE_API_KEY", "") or ""
        provided = request.headers.get("X-API-Key", "") or ""
        if not expected or not provided:
            return False
        return hmac.compare_digest(provided.encode(), expected.encode())

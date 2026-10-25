"""
The unified admin console: SMARTTT's admin functions, called by the Smart
Attendance backend on behalf of an administrator signed in to its admin portal.

There is one admin console for the platform, the Smart Attendance admin
portal. An administrator signs in there with their SMARTTT account (checked by
attendance/authenticate/, which marks them `is_admin`), and the portal's
SMARTTT pages (master timetable upload, terms, lecturer allocation,
notifications, staff IDs, venue capacities) go through the attendance backend
to the endpoints under integrations/admin/, which are SMARTTT's own admin
views with this authentication in front:

    X-API-Key: <ATTENDANCE_API_KEY>          the attendance backend is calling
    X-Acting-Account: <SMARTTT user id>      on behalf of this administrator

The request then runs as that administrator, so every view keeps its own
permission checks and records who did what, exactly as when the
administrator uses SMARTTT directly. The account is re-checked on every call:
someone who is no longer an administrator here is refused at once, even with
a session still open in the console.
"""
from __future__ import annotations

import hmac
import uuid

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from apps.accounts.models import User

from .services import is_console_admin

ACTING_ACCOUNT_HEADER = "X-Acting-Account"


def _error(code: str, detail: str) -> dict[str, str]:
    # {"detail", "code"} in the body, as the other integrations answer, so the
    # caller can tell these apart from a view's own permission refusal.
    return {"detail": detail, "code": code}


class ActingAdminAuthentication(BaseAuthentication):
    """
    401 `invalid_api_key`: the key is missing or wrong (the two systems are
    misconfigured). 403 `not_admin`: the key is right but the acting account is
    unknown, inactive or not an administrator.
    """

    def authenticate(self, request):
        expected = getattr(settings, "ATTENDANCE_API_KEY", "") or ""
        presented = request.headers.get("X-API-Key", "") or ""
        # Fails closed: with ATTENDANCE_API_KEY unset, nothing gets in.
        if not expected or not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
            raise AuthenticationFailed(_error("invalid_api_key", "A valid X-API-Key header is required."))

        raw = (request.headers.get(ACTING_ACCOUNT_HEADER, "") or "").strip()
        try:
            account_id = uuid.UUID(raw)
        except ValueError:
            raise PermissionDenied(_error("not_admin", "Name the acting administrator's SMARTTT account."))
        user = User.objects.filter(pk=account_id).first()
        if user is None or not is_console_admin(user):
            raise PermissionDenied(_error("not_admin", "This account is not a SMARTTT administrator."))
        return (user, None)

    def authenticate_header(self, request):
        # Any value makes DRF answer a failed key with 401 rather than 403.
        return "X-API-Key"

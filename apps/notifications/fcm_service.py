"""
Firebase Cloud Messaging service.
Sends push notifications via FCM HTTP v1 API using a service account.

Setup:
1. Firebase Console → Project Settings → Service Accounts → Generate new private key
2. Save the JSON file securely
3. Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json in .env
   OR set FIREBASE_SERVICE_ACCOUNT_JSON=<contents of JSON> as an env var

We use the google-auth library (already installed as a Firebase dependency)
to get an access token, then call the FCM HTTP v1 API directly.
No extra package needed.
"""
import json
import logging
import os

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

FCM_ENDPOINT = (
    "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
)
FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def _get_credentials():
    """
    Load service account credentials from env var or file.
    Priority:
      1. FIREBASE_SERVICE_ACCOUNT_JSON env var (Render secret env)
      2. GOOGLE_APPLICATION_CREDENTIALS file path
    """
    json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if json_str:
        info = json.loads(json_str)
        return service_account.Credentials.from_service_account_info(
            info, scopes=FCM_SCOPES
        )

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        return service_account.Credentials.from_service_account_file(
            credentials_path, scopes=FCM_SCOPES
        )

    raise EnvironmentError(
        "Neither FIREBASE_SERVICE_ACCOUNT_JSON nor "
        "GOOGLE_APPLICATION_CREDENTIALS is set."
    )


def _get_access_token() -> str:
    credentials = _get_credentials()
    credentials.refresh(Request())
    return credentials.token


def send_to_token(token: str, title: str, body: str, data: dict = None) -> bool:
    """Send a push notification to a single FCM device token."""
    project_id = os.getenv("FIREBASE_PROJECT_ID", "smart-timetable-8f116")
    url = FCM_ENDPOINT.format(project_id=project_id)

    try:
        access_token = _get_access_token()
    except Exception as exc:
        logger.error("FCM credentials error: %s", exc)
        return False

    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in (data or {}).items()},
            "android": {
                "priority": "high",
                "notification": {"sound": "default", "click_action": "FLUTTER_NOTIFICATION_CLICK"},
            },
            "apns": {
                "payload": {"aps": {"sound": "default"}},
            },
            "webpush": {
                "notification": {"icon": "/Icon-192.png"},
            },
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning("FCM send failed for token %s…: %s", token[:20], resp.text)
        return False
    except requests.RequestException as exc:
        logger.error("FCM request error: %s", exc)
        return False


def send_to_tokens(tokens: list[str], title: str, body: str, data: dict = None) -> int:
    """
    Send to multiple tokens. Returns count of successful sends.
    FCM v1 doesn't support multicast natively in the HTTP API,
    so we send individually. For large audiences this should be
    moved to a Celery task — acceptable for university scale.
    """
    success = 0
    for token in tokens:
        if send_to_token(token, title, body, data):
            success += 1
    return success

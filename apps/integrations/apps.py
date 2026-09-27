from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """
    Read-only endpoints for other university systems (server-to-server).

    No models of its own: everything here reads from the timetable, units and
    courses apps. Callers authenticate with a shared API key, never a user JWT.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"

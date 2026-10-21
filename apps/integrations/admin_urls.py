"""
integrations/admin/: SMARTTT's admin functions for the unified admin console
(acting_admin.py). Each route is the same view SMARTTT's own API serves at
the path in the comment, with ActingAdminAuthentication in place of a JWT;
the views' permission checks are unchanged.
"""
from django.urls import path

from apps.accounts.views.auth_views import (
    StaffIDDeleteView,
    StaffIDListView,
    StaffIDUploadDeleteView,
    StaffIDUploadListView,
    StaffIDUploadView,
)
from apps.notifications.views import NotificationListView, SendNotificationView
from apps.programs.views import ProgramViewSet
from apps.rooms.views import RoomViewSet
from apps.timetable.views.allocation_views import AssignLecturersAPIView
from apps.timetable.views.timetable_viewsets import (
    AcademicTermViewSet,
    TimetableUploadAPIView,
    TimetableUploadDeleteAPIView,
    TimetableUploadListViewSet,
    TimetableUploadStatusAPIView,
)

from .acting_admin import ActingAdminAuthentication

AS_ADMIN = {"authentication_classes": [ActingAdminAuthentication]}


def view(cls):
    return cls.as_view(**AS_ADMIN)


def viewset(cls, actions: dict[str, str]):
    """
    A viewset's routes, as a router would build them: an @action's own
    settings (its permission and parser classes) come with it.
    """
    initkwargs: dict = {}
    for name in set(actions.values()):
        func = getattr(cls, name)
        if hasattr(func, "mapping"):  # an @action
            initkwargs.update(func.kwargs)
            initkwargs["detail"] = func.detail
    return cls.as_view(actions, **initkwargs, **AS_ADMIN)


urlpatterns = [
    # timetable/terms/
    path("terms/", viewset(AcademicTermViewSet, {"get": "list", "post": "create"}), name="admin-terms"),
    path(
        "terms/<uuid:pk>/",
        viewset(AcademicTermViewSet, {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="admin-term",
    ),
    path("terms/<uuid:pk>/set-current/", viewset(AcademicTermViewSet, {"post": "set_current"}), name="admin-term-set-current"),
    path("terms/<uuid:pk>/clear-slots/", viewset(AcademicTermViewSet, {"delete": "clear_slots"}), name="admin-term-clear-slots"),
    # timetable/upload/...
    path("timetable/upload/", view(TimetableUploadAPIView), name="admin-timetable-upload"),
    path("timetable/upload/list/", viewset(TimetableUploadListViewSet, {"get": "list"}), name="admin-timetable-upload-list"),
    path("timetable/upload/<uuid:batch_id>/status/", view(TimetableUploadStatusAPIView), name="admin-timetable-upload-status"),
    path("timetable/upload/<uuid:batch_id>/delete/", view(TimetableUploadDeleteAPIView), name="admin-timetable-upload-delete"),
    # timetable/assign-lecturers/
    path("timetable/assign-lecturers/", view(AssignLecturersAPIView), name="admin-assign-lecturers"),
    # notifications/send/, notifications/
    path("notifications/send/", view(SendNotificationView), name="admin-notifications-send"),
    path("notifications/", view(NotificationListView), name="admin-notifications"),
    # auth/staff-ids/...
    path("staff-ids/", view(StaffIDListView), name="admin-staff-ids"),
    path("staff-ids/upload/", view(StaffIDUploadView), name="admin-staff-ids-upload"),
    path("staff-ids/uploads/", view(StaffIDUploadListView), name="admin-staff-id-uploads"),
    path("staff-ids/uploads/<uuid:pk>/", view(StaffIDUploadDeleteView), name="admin-staff-id-upload-delete"),
    path("staff-ids/<uuid:pk>/", view(StaffIDDeleteView), name="admin-staff-id-delete"),
    # rooms/rooms/upload/, rooms/rooms/capacity-summary/
    path("rooms/upload/", viewset(RoomViewSet, {"post": "upload"}), name="admin-rooms-upload"),
    path("rooms/capacity-summary/", viewset(RoomViewSet, {"get": "capacity_summary"}), name="admin-rooms-capacity"),
    # programs/programs/ (the old admin page asked for core/programs/, which never existed)
    path("programs/", viewset(ProgramViewSet, {"get": "list"}), name="admin-programs"),
]

from django.urls import include, path

from .directory_views import AttendanceDepartmentsView, AttendanceFacultiesView
from .generator_views import GeneratorPublicationView, GeneratorPublishView

from .views import (
    AttendanceAuthenticateView,
    AttendanceLecturerUnitsView,
    AttendanceStaffLookupView,
    AttendanceStudentLookupView,
    AttendanceStudentUnitsView,
)

urlpatterns = [
    path(
        "attendance/authenticate/",
        AttendanceAuthenticateView.as_view(),
        name="integrations-attendance-authenticate",
    ),
    path(
        "attendance/lecturer-units/",
        AttendanceLecturerUnitsView.as_view(),
        name="integrations-attendance-lecturer-units",
    ),
    path(
        "attendance/students/",
        AttendanceStudentLookupView.as_view(),
        name="integrations-attendance-student",
    ),
    path(
        "attendance/staff/",
        AttendanceStaffLookupView.as_view(),
        name="integrations-attendance-staff",
    ),
    path(
        "attendance/student-units/",
        AttendanceStudentUnitsView.as_view(),
        name="integrations-attendance-student-units",
    ),
    path(
        "attendance/faculties/",
        AttendanceFacultiesView.as_view(),
        name="integrations-attendance-faculties",
    ),
    path(
        "attendance/departments/",
        AttendanceDepartmentsView.as_view(),
        name="integrations-attendance-departments",
    ),
    # The Timetable Generator publishes approved timetables (generator_publish.py).
    path("generator/publish/", GeneratorPublishView.as_view(), name="integrations-generator-publish"),
    path(
        "generator/publish/<int:version>/",
        GeneratorPublicationView.as_view(),
        name="integrations-generator-publication",
    ),
    # SMARTTT's admin functions for the unified admin console (acting_admin.py).
    path("admin/", include("apps.integrations.admin_urls")),
]

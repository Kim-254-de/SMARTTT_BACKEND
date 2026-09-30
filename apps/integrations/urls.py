from django.urls import path

from .views import (
    AttendanceLecturerUnitsView,
    AttendanceStaffLookupView,
    AttendanceStudentLookupView,
    AttendanceStudentUnitsView,
)

urlpatterns = [
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
]

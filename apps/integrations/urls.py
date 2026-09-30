from django.urls import path

from .views import AttendanceLecturerUnitsView, AttendanceStudentLookupView

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
]

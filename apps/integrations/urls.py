from django.urls import path

from .views import AttendanceLecturerUnitsView

urlpatterns = [
    path(
        "attendance/lecturer-units/",
        AttendanceLecturerUnitsView.as_view(),
        name="integrations-attendance-lecturer-units",
    ),
]

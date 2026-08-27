from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/departments/", include("apps.departments.urls")),
    path("api/v1/programs/", include("apps.programs.urls")),
    path("api/v1/rooms/", include("apps.rooms.urls")),
    path("api/v1/lecturers/", include("apps.lecturers.urls")),
    path("api/v1/units/", include("apps.units.urls")),
    path("api/v1/students/", include("apps.students.urls")),
    path("api/v1/enrollments/", include("apps.enrollments.urls")),
    path("api/v1/timetable/", include("apps.timetable.urls")),
    path("api/v1/courses/", include("apps.courses.urls")),
    path("api/v1/schedule/", include("apps.schedule.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
]

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/core/", include("apps.core.urls")),
    path("api/v1/timetable/", include("apps.timetable.urls")),
    path("api/v1/courses/", include("apps.courses.urls")),
    path("api/v1/schedule/", include("apps.schedule.urls")),
]

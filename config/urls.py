from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
	path("admin/", admin.site.urls),
	path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
	path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
	path("api/v1/accounts/", include("apps.accounts.urls")),
	path("api/v1/students/", include("apps.students.urls")),
	path("api/v1/lecturers/", include("apps.lecturers.urls")),
	path("api/v1/departments/", include("apps.departments.urls")),
	path("api/v1/programs/", include("apps.programs.urls")),
	path("api/v1/units/", include("apps.units.urls")),
	path("api/v1/curriculum/", include("apps.curriculum.urls")),
	path("api/v1/timetable/", include("apps.timetable.urls")),
	path("api/v1/enrollments/", include("apps.enrollments.urls")),
	path("api/v1/rooms/", include("apps.rooms.urls")),
	path("api/v1/analytics/", include("apps.analytics.urls")),
]

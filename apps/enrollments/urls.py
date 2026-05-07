from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.enrollments.views import StudentEnrollmentViewSet

router = DefaultRouter()
router.register("student-enrollments", StudentEnrollmentViewSet, basename="student-enrollments")

urlpatterns = [path("", include(router.urls))]

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.lecturers.views import LecturerViewSet

router = DefaultRouter()
router.register("lecturers", LecturerViewSet, basename="lecturers")

urlpatterns = [path("", include(router.urls))]

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.programs.views import ProgramViewSet

router = DefaultRouter()
router.register("programs", ProgramViewSet, basename="programs")

urlpatterns = [path("", include(router.urls))]

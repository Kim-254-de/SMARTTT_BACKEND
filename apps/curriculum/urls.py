from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.curriculum.views import CurriculumUnitViewSet, CurriculumViewSet

router = DefaultRouter()
router.register("curricula", CurriculumViewSet, basename="curricula")
router.register("curriculum-units", CurriculumUnitViewSet, basename="curriculum-units")

urlpatterns = [path("", include(router.urls))]

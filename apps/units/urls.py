from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.units.views import UnitViewSet

router = DefaultRouter()
router.register("units", UnitViewSet, basename="units")

urlpatterns = [path("", include(router.urls))]

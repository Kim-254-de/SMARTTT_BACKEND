from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.analytics.views import TimetableMetricViewSet

router = DefaultRouter()
router.register("timetable-metrics", TimetableMetricViewSet, basename="timetable-metrics")

urlpatterns = [path("", include(router.urls))]

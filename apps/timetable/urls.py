from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.timetable.views import (
    AcademicTermViewSet,
    TimetableConflictViewSet,
    TimetableSlotViewSet,
    TimetableUploadAPIView,
)

router = DefaultRouter()
router.register("terms", AcademicTermViewSet, basename="terms")
router.register("slots", TimetableSlotViewSet, basename="slots")
router.register("conflicts", TimetableConflictViewSet, basename="conflicts")

urlpatterns = [
    path("", include(router.urls)),
    path("upload/", TimetableUploadAPIView.as_view(), name="timetable-upload"),
]

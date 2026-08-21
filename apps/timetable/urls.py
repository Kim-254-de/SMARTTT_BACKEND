from django.urls import include, path
from rest_framework.routers import DefaultRouter
from apps.units.views import UnitViewSet
from apps.timetable.views.timetable_viewsets import (
    AcademicTermViewSet,
    TimetableUploadAPIView,
    TimetableUploadListViewSet,
)
from apps.timetable.views.viewsets import RoomViewSet, TimeSlotViewSet, TimetableSessionViewSet

router = DefaultRouter()
router.register("terms", AcademicTermViewSet, basename="term")
router.register("units", UnitViewSet, basename="unit")
router.register("rooms", RoomViewSet, basename="room")
router.register("time-slots", TimeSlotViewSet, basename="time-slot")
router.register("sessions", TimetableSessionViewSet, basename="session")

urlpatterns = [
    path("", include(router.urls)),
    path("upload/", TimetableUploadAPIView.as_view(), name="timetable-upload"),
    path("upload/list/", TimetableUploadListViewSet.as_view({"get": "list"}), name="timetable-upload-list"),
]

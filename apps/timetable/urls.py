from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AcademicTermViewSet, TimetableSlotListView,
    TimetableUploadDetailView, TimetableUploadView, UnitViewSet,
)

router = DefaultRouter()
router.register("terms", AcademicTermViewSet, basename="term")
router.register("units", UnitViewSet, basename="unit")

urlpatterns = [
    path("", include(router.urls)),
    path("slots/", TimetableSlotListView.as_view(), name="timetable-slots"),
    path("upload/", TimetableUploadView.as_view(), name="timetable-upload"),
    path("upload/<uuid:pk>/", TimetableUploadDetailView.as_view(), name="timetable-upload-detail"),
]

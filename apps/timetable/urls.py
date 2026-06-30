from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AcademicTermViewSet, AcademicTermSetCurrentView, TimetableSlotListView,
    TimetableSlotsClearView, TimetableUploadDeleteView, TimetableUploadDetailView,
    TimetableUploadListView, TimetableUploadView, UnitViewSet,
)

router = DefaultRouter()
router.register("terms", AcademicTermViewSet, basename="term")
router.register("units", UnitViewSet, basename="unit")

urlpatterns = [
    path("", include(router.urls)),
    path("slots/", TimetableSlotListView.as_view(), name="timetable-slots"),
    path("upload/", TimetableUploadView.as_view(), name="timetable-upload"),
    path("upload/list/", TimetableUploadListView.as_view(), name="timetable-upload-list"),
    path("upload/<uuid:pk>/", TimetableUploadDetailView.as_view(), name="timetable-upload-detail"),
    path("upload/<uuid:pk>/delete/", TimetableUploadDeleteView.as_view(), name="timetable-upload-delete"),
    path("terms/<uuid:pk>/set-current/", AcademicTermSetCurrentView.as_view(), name="term-set-current"),
    path("terms/<uuid:pk>/clear-slots/", TimetableSlotsClearView.as_view(), name="term-clear-slots"),
]

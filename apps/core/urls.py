from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import DepartmentViewSet, FacultyViewSet, LecturerViewSet, ProgramViewSet, RoomViewSet

router = DefaultRouter()
router.register("faculties", FacultyViewSet, basename="faculty")
router.register("departments", DepartmentViewSet, basename="department")
router.register("programs", ProgramViewSet, basename="program")
router.register("rooms", RoomViewSet, basename="room")
router.register("lecturers", LecturerViewSet, basename="lecturer")

urlpatterns = [path("", include(router.urls))]

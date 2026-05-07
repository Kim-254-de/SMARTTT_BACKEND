from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.students.views import StudentViewSet

router = DefaultRouter()
router.register("students", StudentViewSet, basename="students")

urlpatterns = [path("", include(router.urls))]

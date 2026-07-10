from django.urls import path
from .views import ManualSyncView, MyCoursesView, PortalSyncView

urlpatterns = [
    path("sync/portal/", PortalSyncView.as_view(), name="courses-sync-portal"),
    path("sync/manual/", ManualSyncView.as_view(), name="courses-sync-manual"),
    path("my-courses/", MyCoursesView.as_view(), name="my-courses"),
]

from django.urls import path
from .views import ManualSyncView, MyCoursesView, PortalSyncView, SetUnitGroupView

urlpatterns = [
    path("sync/portal/", PortalSyncView.as_view(), name="courses-sync-portal"),
    path("sync/manual/", ManualSyncView.as_view(), name="courses-sync-manual"),
    path("my-courses/", MyCoursesView.as_view(), name="my-courses"),
    path("my-courses/<uuid:pk>/group/", SetUnitGroupView.as_view(), name="my-courses-set-group"),
]

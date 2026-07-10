from django.urls import path
from .views import MyScheduleView

urlpatterns = [
    path("me/", MyScheduleView.as_view(), name="my-schedule"),
]

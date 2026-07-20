from django.urls import path
from .views import MyScheduleView, MyCalendarFeedView

urlpatterns = [
    path("me/", MyScheduleView.as_view(), name="my-schedule"),
    path('calendar.ics', MyCalendarFeedView.as_view(), name="my-calendar-feed"),
]

from django.urls import path
from .views import MyScheduleView, MyCalendarFeedView, CalendarTokenView

urlpatterns = [
    path("me/", MyScheduleView.as_view(), name="my-schedule"),
    path("calendar-token/", CalendarTokenView.as_view(), name="my-calendar-token"),
    path('calendar.ics', MyCalendarFeedView.as_view(), name="my-calendar-feed"),
]
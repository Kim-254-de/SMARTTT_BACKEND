from django.urls import path
from .views import MyExamsView, MyScheduleView, MyCalendarFeedView, CalendarTokenView

urlpatterns = [
    path("me/", MyScheduleView.as_view(), name="my-schedule"),
    path("exams/me/", MyExamsView.as_view(), name="my-exams"),
    path("calendar-token/", CalendarTokenView.as_view(), name="my-calendar-token"),
    path('calendar.ics', MyCalendarFeedView.as_view(), name="my-calendar-feed"),
]
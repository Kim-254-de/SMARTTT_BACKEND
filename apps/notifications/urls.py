from django.urls import path
from .views import (
    MarkNotificationReadView, MyNotificationsView,
    NotificationListView, RegisterFCMTokenView,
    SendNotificationView, UnreadCountView,
    LecturerSendNotificationView,
)

urlpatterns = [
    path("register-token/", RegisterFCMTokenView.as_view(), name="register-fcm-token"),
    path("send/", SendNotificationView.as_view(), name="send-notification"),
    path("", NotificationListView.as_view(), name="notification-list"),
    path("mine/", MyNotificationsView.as_view(), name="my-notifications"),
    path("unread-count/", UnreadCountView.as_view(), name="unread-count"),
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="mark-read"),
    path("lecturer/send/", LecturerSendNotificationView.as_view(), name="lecturer-send"),
]

from django.contrib import admin
from .models import FCMToken, Notification, StudentNotification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "notification_type", "target", "recipients_count", "sent_by", "sent_at"]
    list_filter = ["notification_type", "target", "sent_at"]
    search_fields = ["title", "message"]
    readonly_fields = ["sent_at", "recipients_count"]

@admin.register(FCMToken)
class FCMTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "updated_at"]
    list_filter = ["platform"]
    search_fields = ["user__email"]

@admin.register(StudentNotification)
class StudentNotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "notification", "is_read", "delivered_at"]
    list_filter = ["is_read"]

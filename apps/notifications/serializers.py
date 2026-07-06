from rest_framework import serializers
from .models import FCMToken, Notification, StudentNotification


class FCMTokenSerializer(serializers.Serializer):
    token = serializers.CharField()
    platform = serializers.ChoiceField(
        choices=FCMToken.Platform.choices,
        default=FCMToken.Platform.ANDROID,
    )


class SendNotificationSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    message = serializers.CharField()
    notification_type = serializers.ChoiceField(
        choices=Notification.Type.choices,
        default=Notification.Type.GENERAL,
    )
    target = serializers.ChoiceField(
        choices=Notification.Target.choices,
        default=Notification.Target.ALL,
    )
    target_program = serializers.UUIDField(required=False, allow_null=True)
    target_year = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=6)


class NotificationSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.CharField(source="sent_by.get_full_name", read_only=True)
    target_program_name = serializers.CharField(
        source="target_program.name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = [
            "id", "title", "message", "notification_type",
            "target", "target_program", "target_program_name",
            "target_year", "recipients_count", "sent_by",
            "sent_by_name", "sent_at",
        ]


class StudentNotificationSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="notification.title", read_only=True)
    message = serializers.CharField(source="notification.message", read_only=True)
    notification_type = serializers.CharField(
        source="notification.notification_type", read_only=True
    )
    sent_at = serializers.DateTimeField(source="notification.sent_at", read_only=True)

    class Meta:
        model = StudentNotification
        fields = [
            "id", "title", "message", "notification_type",
            "is_read", "read_at", "delivered_at", "sent_at",
        ]

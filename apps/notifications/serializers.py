from rest_framework import serializers
from apps.rooms.models import Room
from .models import FCMToken, Notification, NotificationType, StudentNotification, Target


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
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    target = serializers.ChoiceField(
        choices=Target.choices,
        default=Target.ALL,
    )
    target_program = serializers.UUIDField(required=False, allow_null=True)
    target_year = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=6)

class LecturerVenueChangeSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    message = serializers.CharField()
    unit_id = serializers.CharField()
    new_venue_id = serializers.UUIDField()
    expected_students = serializers.IntegerField(min_value=1)

    def validate(self, data):
        try:
            room = Room.objects.get(pk=data["new_venue_id"])
        except Room.DoesNotExist:
            raise serializers.ValidationError({"new_venue_id": "Room not found."})

        if room.capacity == 0:
            raise serializers.ValidationError({
                "new_venue_id": f"{room.code} has no recorded capacity — cannot verify fit."
            })

        if data["expected_students"] > room.capacity:
            suggestions = list(
                Room.objects.filter(capacity__gte=data["expected_students"])
                .exclude(capacity=0)
                .order_by("capacity")
                .values("code", "capacity")[:5]
            )
            raise serializers.ValidationError({
                "capacity_error": (
                    f"{room.code} holds {room.capacity} students, "
                    f"but {data['expected_students']} are expected."
                ),
                "suggested_rooms": suggestions,
            })

        data["room_obj"] = room
        return data
class NotificationSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.SerializerMethodField()
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

    def get_sent_by_name(self, obj):
        return obj.sent_by.get_full_name() if obj.sent_by else "SMARTTT"


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

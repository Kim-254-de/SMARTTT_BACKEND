from rest_framework import serializers

from apps.rooms.models import Room


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = "__all__"
        read_only_fields = ["capacity_confirmed"]

    def validate(self, attrs):
        # An admin entering a capacity by hand is as good as uploading it.
        if "capacity" in attrs:
            attrs["capacity_confirmed"] = True
        return attrs

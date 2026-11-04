from rest_framework import serializers

from apps.rooms.models import Room


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = "__all__"
        read_only_fields = ["capacity_confirmed"]

    def validate_code(self, value):
        # "TC1" and "TC 1" are one room: a second code for it would split its bookings.
        from apps.rooms.services.room_merge import find_twin

        twin = find_twin(value, exclude_pk=self.instance.pk if self.instance else None)
        if twin is not None:
            raise serializers.ValidationError(f"This is the same room as {twin.code}.")
        return value

    def validate(self, attrs):
        # An admin entering a capacity by hand is as good as uploading it.
        if "capacity" in attrs:
            attrs["capacity_confirmed"] = True
        return attrs

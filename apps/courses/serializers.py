from rest_framework import serializers
from apps.timetable.models import Unit
from .models import StudentUnit


class PortalSyncSerializer(serializers.Serializer):
    """Used by the scrape-and-sync endpoint."""
    portal_username = serializers.CharField()
    portal_password = serializers.CharField(write_only=True)


class ManualSyncSerializer(serializers.Serializer):
    """Used by the manual unit entry endpoint."""
    unit_codes = serializers.ListField(child=serializers.CharField(), min_length=1)


class StudentUnitSerializer(serializers.ModelSerializer):
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    term_label = serializers.CharField(source="term.__str__", read_only=True)
    available_groups = serializers.SerializerMethodField()

    class Meta:
        model = StudentUnit
        fields = [
            "id", "unit", "unit_code", "unit_name", "term", "term_label",
            "synced_at", "class_group", "available_groups",
        ]
        read_only_fields = ["class_group"]

    def get_available_groups(self, obj):
        # Non-empty only when this unit is actually split into more than one
        # elective/practical group for the student's program+stream - see
        # apps.schedule.services.available_groups_for_unit. Group letters
        # are unrelated between different unit pools within the same
        # stream, so this is computed per-unit, not once for the student.
        from apps.schedule.services import available_groups_for_unit
        request = self.context.get("request")
        if not request:
            return []
        return available_groups_for_unit(request.user, obj.term, obj.unit_id)


class SetUnitGroupSerializer(serializers.Serializer):
    """Used by PATCH /courses/my-courses/{id}/group/."""
    class_group = serializers.CharField(allow_blank=True)

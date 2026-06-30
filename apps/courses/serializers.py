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

    class Meta:
        model = StudentUnit
        fields = ["id", "unit", "unit_code", "unit_name", "term", "term_label", "synced_at"]

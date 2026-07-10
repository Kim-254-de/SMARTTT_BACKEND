from rest_framework import serializers
from .models import AcademicTerm, TimetableSlot, TimetableUpload, Unit


class AcademicTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicTerm
        fields = ["id", "academic_year", "semester", "start_date", "end_date", "is_current"]


class UnitSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Unit
        fields = ["id", "code", "name", "department", "department_name", "credit_hours"]


class TimetableSlotSerializer(serializers.ModelSerializer):
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    room_code = serializers.CharField(source="room.code", read_only=True, default=None)
    lecturer_name = serializers.SerializerMethodField()
    term_label = serializers.CharField(source="term.__str__", read_only=True)

    class Meta:
        model = TimetableSlot
        fields = [
            "id", "term", "term_label", "unit", "unit_code", "unit_name",
            "program", "program_name", "year_of_study",
            "lecturer", "lecturer_name", "room", "room_code",
            "day", "start_time", "end_time",
        ]

    def get_lecturer_name(self, obj):
        if obj.lecturer:
            return obj.lecturer.user.get_full_name()
        return None


class TimetableUploadSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True)

    class Meta:
        model = TimetableUpload
        fields = [
            "id", "uploaded_by", "uploaded_by_name", "uploaded_file",
            "term", "status", "rows_received", "rows_saved", "rows_failed",
            "errors", "uploaded_at", "processed_at",
        ]
        read_only_fields = [
            "uploaded_by", "status", "rows_received", "rows_saved",
            "rows_failed", "errors", "uploaded_at", "processed_at",
        ]

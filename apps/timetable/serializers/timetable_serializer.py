from rest_framework import serializers
from datetime import time

from apps.timetable.models import (
    AcademicTerm,
    TimetableConflict,
    TimetableSlot,
    TimetableUploadBatch,
)


class AcademicTermSerializer(serializers.ModelSerializer):
    """Serializer for AcademicTerm model."""
    
    is_active = serializers.SerializerMethodField()
    
    class Meta:
        model = AcademicTerm
        fields = (
            "id",
            "academic_year",
            "semester",
            "start_date",
            "end_date",
            "is_current",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
    
    def get_is_active(self, obj) -> bool:
        """Check if term is currently active."""
        from datetime import date
        today = date.today()
        return obj.start_date <= today <= obj.end_date


class TimetableUploadBatchSerializer(serializers.ModelSerializer):
    """Serializer for TimetableUploadBatch model."""
    
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.get_full_name",
        read_only=True
    )
    validation_error_count = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    
    class Meta:
        model = TimetableUploadBatch
        fields = (
            "id",
            "uploaded_by",
            "uploaded_by_name",
            "source_file",
            "status",
            "rows_received",
            "rows_saved",
            "validation_error_count",
            "success_rate",
            "validation_errors",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "rows_received",
            "rows_saved",
            "validation_errors",
            "created_at",
            "updated_at",
        )
    
    def get_validation_error_count(self, obj) -> int:
        if isinstance(obj.validation_errors, list):
            return len(obj.validation_errors)
        return 0
    
    def get_success_rate(self, obj) -> float:
        """Calculate success rate percentage."""
        if obj.rows_received == 0:
            return 0.0
        return round((obj.rows_saved / obj.rows_received) * 100, 2)


class TimetableSlotDetailedSerializer(serializers.ModelSerializer):
    term_display = serializers.CharField(source="term.__str__", read_only=True)
    unit_display = serializers.CharField(source="unit.__str__", read_only=True)
    program_display = serializers.CharField(source="program.__str__", read_only=True)
    lecturer_display = serializers.SerializerMethodField()
    room_display = serializers.CharField(source="room.code", read_only=True)
    day_display = serializers.CharField(source="get_day_of_week_display", read_only=True)

    class Meta:
        model = TimetableSlot
        fields = (
            "id",
            "term",
            "term_display",
            "unit",
            "unit_display",
            "program",
            "program_display",
            "year_of_study",
            "lecturer",
            "lecturer_display",
            "room",
            "room_display",
            "day_of_week",
            "day_display",
            "start_time",
            "end_time",
            "class_group",
            "upload_batch",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_lecturer_display(self, obj) -> str:
        if obj.lecturer and hasattr(obj.lecturer, "user") and obj.lecturer.user:
            name = obj.lecturer.user.get_full_name().strip()
            if name:
                return name
        return getattr(obj, "lecturer_name_text", "") or ""

    def get_lecturer_display(self, obj) -> str:
        if obj.lecturer and hasattr(obj.lecturer, "user") and obj.lecturer.user:
            name = obj.lecturer.user.get_full_name().strip()
            if name:
                return name
        return getattr(obj, "lecturer_name_text", "") or ""


class TimetableSlotSerializer(serializers.ModelSerializer):
    """Standard serializer for TimetableSlot model."""

    subject = serializers.CharField(source="unit.name", read_only=True)
    instructor = serializers.SerializerMethodField()
    location = serializers.CharField(source="room.code", read_only=True)

    curriculum_unit_display = serializers.CharField(
        source="unit.__str__",
        read_only=True,
    )
    lecturer_display = serializers.SerializerMethodField()
    room_display = serializers.CharField(source="room.code", read_only=True)
    
    class Meta:
        model = TimetableSlot
        fields = (
            "id",
            "term",
            "unit",
            "program",
            "year_of_study",
            "lecturer",
            "lecturer_display",
            "room",
            "room_display",
            "day_of_week",
            "start_time",
            "end_time",
            "class_group",
            "upload_batch",
            "created_at",
            "curriculum_unit_display",

            # Frontend-friendly aliases
            "subject",
            "instructor",
            "location",
        )
        read_only_fields = ("id", "created_at")

    def get_instructor(self, obj) -> str:
        # 1. First check if a registered Lecturer user account exists
        if obj.lecturer and hasattr(obj.lecturer, "user") and obj.lecturer.user:
            name = obj.lecturer.user.get_full_name().strip()
            if name:
                return name
        # 2. Fall back to the name parsed from the .docx file!
        return getattr(obj, "lecturer_name_text", "") or ""

    def get_lecturer_display(self, obj) -> str:
        return self.get_instructor(obj)


class TimetableSlotRescheduleSerializer(serializers.Serializer):
    """
    Deliberately narrow: only the fields a reschedule is allowed to touch.
    Unlike TimetableSlotSerializer, this can never be used to change the
    unit, program, lecturer, or class_group on a slot.
    """
    day_of_week = serializers.ChoiceField(choices=TimetableSlot.WeekDay.choices, required=False)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    room = serializers.PrimaryKeyRelatedField(
        queryset=TimetableSlot._meta.get_field("room").related_model.objects.all(),
        required=False,
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, data):
        if not any(k in data for k in ("day_of_week", "start_time", "end_time", "room")):
            raise serializers.ValidationError(
                "Provide at least one of day_of_week, start_time, end_time, room."
            )

        instance = self.instance
        start_time = data.get("start_time", instance.start_time if instance else None)
        end_time = data.get("end_time", instance.end_time if instance else None)
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({"end_time": "Must be after start_time."})
        return data


class ConflictDetailSerializer(serializers.ModelSerializer):
    """Serializer for conflict details with slot information."""
    
    slot_a_details = TimetableSlotDetailedSerializer(source="slot_a", read_only=True)
    slot_b_details = TimetableSlotDetailedSerializer(source="slot_b", read_only=True)
    conflict_type_display = serializers.CharField(
        source="get_conflict_type_display",
        read_only=True
    )
    
    class Meta:
        model = TimetableConflict
        fields = (
            "id",
            "conflict_type",
            "conflict_type_display",
            "term",
            "slot_a",
            "slot_a_details",
            "slot_b",
            "slot_b_details",
            "details",
            "created_at",
        )
        read_only_fields = fields


class TimetableConflictSerializer(serializers.ModelSerializer):
    """Standard serializer for TimetableConflict model."""
    
    class Meta:
        model = TimetableConflict
        fields = (
            "id",
            "conflict_type",
            "term",
            "slot_a",
            "slot_b",
            "details",
            "created_at",
        )
        read_only_fields = fields


class TimetableUploadBatchDetailedSerializer(serializers.ModelSerializer):
    """Detailed serializer for upload batch with related slots and conflicts."""
    
    slots = TimetableSlotSerializer(many=True, read_only=True)
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.get_full_name",
        read_only=True
    )
    
    class Meta:
        model = TimetableUploadBatch
        fields = (
            "id",
            "uploaded_by",
            "uploaded_by_name",
            "source_file",
            "status",
            "rows_received",
            "rows_saved",
            "validation_errors",
            "slots",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class UploadResponseSerializer(serializers.Serializer):
    """Serializer for upload API response."""
    
    status = serializers.CharField()
    upload_batch_id = serializers.CharField()
    summary = serializers.DictField()
    errors = serializers.ListField()
    message = serializers.CharField()


class ConflictResponseSerializer(serializers.Serializer):
    """Serializer for conflict detection API response."""
    
    status = serializers.CharField()
    summary = serializers.DictField()
    conflicts = ConflictDetailSerializer(many=True)
    message = serializers.CharField()


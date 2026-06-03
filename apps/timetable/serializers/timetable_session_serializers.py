from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.timetable.models import TimetableSession
from apps.units.serializers import UnitSerializer
from apps.lecturers.serializers import LecturerSerializer
from apps.programs.serializers import ProgramSerializer
from apps.departments.serializers import DepartmentSerializer


class TimetableSessionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing timetable sessions."""

    unit_code = serializers.CharField(source="unit.code", read_only=True)
    unit_title = serializers.CharField(source="unit.name", read_only=True)
    room_code = serializers.CharField(source="room.code", read_only=True, allow_null=True)
    room_name = serializers.CharField(source="room.name", read_only=True, allow_null=True)
    lecturer_name = serializers.SerializerMethodField(read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    department_code = serializers.CharField(source="department.code", read_only=True)
    day_display = serializers.CharField(source="get_day_display", read_only=True)
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    time_range = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TimetableSession
        fields = [
            "id",
            "unit_code",
            "unit_title",
            "program_name",
            "department_code",
            "day_display",
            "day_of_week",
            "time_range",
            "room_code",
            "room_name",
            "lecturer_name",
            "session_type",
            "session_type_display",
            "study_year",
            "semester",
            "status",
            "status_display",
            "current_enrollment",
            "max_students",
        ]

    def get_lecturer_name(self, obj) -> str:
        """Get lecturer full name."""
        return obj.lecturer.user.get_full_name() if obj.lecturer else None

    def get_time_range(self, obj) -> str:
        """Get formatted time range."""
        return obj.get_session_time_str()


class TimetableSessionDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer for timetable sessions."""

    unit = UnitSerializer(read_only=True)
    program = ProgramSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    lecturer = LecturerSerializer(read_only=True)
    day_display = serializers.CharField(source="get_day_display", read_only=True)
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    delivery_mode_display = serializers.CharField(source="get_delivery_mode_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    time_range = serializers.SerializerMethodField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    available_seats = serializers.IntegerField(read_only=True)
    occupancy_percentage = serializers.FloatField(read_only=True)
    created_by_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TimetableSession
        fields = [
            "id",
            "unit",
            "program",
            "department",
            "lecturer",
            "room",
            "time_slot",
            "academic_year",
            "study_year",
            "semester",
            "day_of_week",
            "day_display",
            "session_type",
            "session_type_display",
            "delivery_mode",
            "delivery_mode_display",
            "student_group",
            "max_students",
            "current_enrollment",
            "is_full",
            "available_seats",
            "occupancy_percentage",
            "status",
            "status_display",
            "time_range",
            "notes",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_full",
            "available_seats",
            "occupancy_percentage",
            "created_at",
            "updated_at",
        ]

    def get_time_range(self, obj) -> str:
        return obj.get_session_time_str()

    def get_created_by_name(self, obj) -> str:
        """Get creator's full name."""
        return obj.created_by.get_full_name() if obj.created_by else None


class TimetableSessionCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating timetable sessions."""

    class Meta:
        model = TimetableSession
        fields = [
            "unit",
            "program",
            "department",
            "lecturer",
            "room",
            "time_slot",
            "academic_year",
            "study_year",
            "semester",
            "day_of_week",
            "session_type",
            "delivery_mode",
            "student_group",
            "max_students",
            "status",
            "notes",
        ]

    def validate_study_year(self, value):
        """Validate study year."""
        if not (1 <= value <= 5):
            raise serializers.ValidationError(_("Study year must be between 1 and 5"))
        return value

    def validate_semester(self, value):
        """Validate semester."""
        if value not in [1, 2]:
            raise serializers.ValidationError(_("Semester must be 1 or 2"))
        return value

    def validate_max_students(self, value):
        """Validate maximum students."""
        if value <= 0:
            raise serializers.ValidationError(_("Maximum students must be greater than 0"))
        if value > 500:
            raise serializers.ValidationError(_("Maximum students cannot exceed 500"))
        return value

    def validate_academic_year(self, value):
        """Validate academic year format."""
        if not value or "/" not in value:
            raise serializers.ValidationError(
                _("Academic year format must be YYYY/YYYY (e.g., 2024/2025)")
            )
        return value

    def validate(self, data):
        """Cross-field validation."""
        unit = data.get("unit")
        department = data.get("department")
        lecturer = data.get("lecturer")
        room = data.get("room")
        max_students = data.get("max_students")

        # Unit and department must match
        if unit and department and unit.department_id != department.id:
            raise serializers.ValidationError(
                {
                    "unit": _("Unit's department must match session's department"),
                }
            )

        # Lecturer must be from same department
        if lecturer and department and lecturer.department_id != department.id:
            raise serializers.ValidationError(
                {
                    "lecturer": _("Lecturer must be from the same department as the session"),
                }
            )

        # Room capacity must accommodate max students
        if room and max_students and max_students > room.capacity:
            raise serializers.ValidationError(
                {
                    "max_students": _(
                        f"Maximum students ({max_students}) exceeds room capacity ({room.capacity})"
                    ),
                }
            )

        return data

    def create(self, validated_data):
        """Create new timetable session."""
        request = self.context.get("request")
        if request and request.user:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class TimetableSessionBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk uploading timetable sessions."""

    sessions = TimetableSessionCreateUpdateSerializer(many=True)

    def create(self, validated_data):
        """Bulk create sessions."""
        sessions_data = validated_data.get("sessions", [])
        created_sessions = []

        for session_data in sessions_data:
            serializer = TimetableSessionCreateUpdateSerializer(data=session_data, context=self.context)
            if serializer.is_valid():
                created_sessions.append(serializer.save())
            else:
                raise serializers.ValidationError(serializer.errors)

        return created_sessions


class StudentTimetableSessionSerializer(serializers.ModelSerializer):
    """
    Serializer for viewing timetable sessions from student perspective.

    Students see only sessions relevant to their program/curriculum.
    """

    unit_code = serializers.CharField(source="unit.code", read_only=True)
    unit_title = serializers.CharField(source="unit.name", read_only=True)
    unit_credit_hours = serializers.IntegerField(source="unit.credit_hours", read_only=True)
    room_code = serializers.CharField(source="room.code", read_only=True, allow_null=True)
    room_name = serializers.CharField(source="room.name", read_only=True, allow_null=True)
    room_building = serializers.CharField(source="room.building", read_only=True, allow_null=True)
    lecturer_name = serializers.SerializerMethodField(read_only=True)
    lecturer_id = serializers.SerializerMethodField(read_only=True)
    day_display = serializers.CharField(source="get_day_display", read_only=True)
    session_type_display = serializers.CharField(source="get_session_type_display", read_only=True)
    time_range = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TimetableSession
        fields = [
            "id",
            "unit_code",
            "unit_title",
            "unit_credit_hours",
            "day_display",
            "day_of_week",
            "time_range",
            "room_code",
            "room_name",
            "room_building",
            "lecturer_name",
            "lecturer_id",
            "session_type",
            "session_type_display",
            "delivery_mode",
            "student_group",
            "max_students",
            "current_enrollment",
        ]
        read_only_fields = fields

    def get_lecturer_name(self, obj) -> str:
        return obj.lecturer.user.get_full_name() if obj.lecturer else None

    def get_lecturer_id(self, obj) -> str:
        return str(obj.lecturer.id) if obj.lecturer else None

    def get_time_range(self, obj) -> str:
        return obj.get_session_time_str()

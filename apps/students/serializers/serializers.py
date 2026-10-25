from rest_framework import serializers
from django.utils.translation import gettext_lazy as _

from apps.students.models import Student, AcademicProgress, StudentEnrollment
from apps.accounts.serializers import UserSerializer  # Assuming exists
from apps.programs.serializers import ProgramSerializer  # Assuming exists
from apps.departments.serializers import DepartmentSerializer  # Assuming exists


class StudentListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing students.
    Used in list views and filtering operations.
    """

    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
    )
    program_name = serializers.CharField(
        source="program.name",
        read_only=True,
    )
    program_code = serializers.CharField(
        source="program.code",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_academic_status_display",
        read_only=True,
    )

    class Meta:
        model = Student
        fields = [
            "id",
            "registration_number",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "department_name",
            "program_name",
            "program_code",
            "current_study_year",
            "current_semester",
            "academic_status",
            "status_display",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class StudentDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for detailed student view.
    Includes related objects and computed fields.
    """

    user = UserSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    program = ProgramSerializer(read_only=True)

    gender_display = serializers.CharField(
        source="get_gender_display",
        read_only=True,
    )
    academic_status_display = serializers.CharField(
        source="get_academic_status_display",
        read_only=True,
    )
    enrollment_type_display = serializers.CharField(
        source="get_enrollment_type_display",
        read_only=True,
    )

    # Computed fields
    full_name = serializers.SerializerMethodField()
    academic_year_string = serializers.SerializerMethodField()
    is_graduated = serializers.SerializerMethodField()
    is_suspended = serializers.SerializerMethodField()
    can_enroll = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "user",
            "registration_number",
            "first_name",
            "last_name",
            "full_name",
            "gender",
            "gender_display",
            "email",
            "phone_number",
            "date_of_birth",
            "department",
            "program",
            "current_study_year",
            "current_semester",
            "admission_year",
            "academic_status",
            "academic_status_display",
            "enrollment_type",
            "enrollment_type_display",
            "is_active",
            "profile_photo",
            "academic_year_string",
            "is_graduated",
            "is_suspended",
            "can_enroll",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "full_name",
            "academic_year_string",
            "is_graduated",
            "is_suspended",
            "can_enroll",
            "created_at",
            "updated_at",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_academic_year_string(self, obj):
        return obj.academic_year_string

    def get_is_graduated(self, obj):
        return obj.is_graduated

    def get_is_suspended(self, obj):
        return obj.is_suspended

    def get_can_enroll(self, obj):
        return obj.can_enroll_in_courses()


class StudentCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating student profiles.
    Validates data and ensures consistency.
    """

    user_id = serializers.UUIDField(required=True)
    department_id = serializers.UUIDField(required=True)
    program_id = serializers.UUIDField(required=True)

    class Meta:
        model = Student
        fields = [
            "registration_number",
            "first_name",
            "last_name",
            "gender",
            "email",
            "phone_number",
            "date_of_birth",
            "user_id",
            "department_id",
            "program_id",
            "current_study_year",
            "current_semester",
            "admission_year",
            "academic_status",
            "enrollment_type",
            "is_active",
            "profile_photo",
        ]

    def validate_registration_number(self, value):
        """Ensure registration number is unique and properly formatted."""
        instance = self.instance
        qs = Student.objects.filter(registration_number=value)

        if instance:
            qs = qs.exclude(pk=instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                _("A student with this registration number already exists.")
            )
        return value

    def validate_email(self, value):
        """Ensure email is unique."""
        instance = self.instance
        qs = Student.objects.filter(email=value)

        if instance:
            qs = qs.exclude(pk=instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                _("A student with this email already exists.")
            )
        return value

    def validate_current_study_year(self, value):
        """Validate study year."""
        if value < 1:
            raise serializers.ValidationError(
                _("Study year must be at least 1.")
            )
        return value

    def validate_current_semester(self, value):
        """Validate semester."""
        if value not in [1, 2]:
            raise serializers.ValidationError(
                _("Semester must be 1 or 2.")
            )
        return value

    def validate_admission_year(self, value):
        """Validate admission year."""
        from django.utils import timezone
        current_year = timezone.now().year

        if value > current_year:
            raise serializers.ValidationError(
                _("Admission year cannot be in the future.")
            )
        return value

    def validate(self, data):
        """Cross-field validation."""
        program_id = data.get("program_id")
        department_id = data.get("department_id")

        if program_id and department_id:
            from apps.programs.models import Program

            try:
                program = Program.objects.get(id=program_id)
                if program.department_id != department_id:
                    raise serializers.ValidationError({
                        "department": _(
                            "Department must match the program's department."
                        )
                    })
            except Program.DoesNotExist:
                raise serializers.ValidationError({
                    "program": _("Program not found.")
                })

        # Validate study year against program duration
        study_year = data.get("current_study_year")
        if program_id and study_year:
            try:
                program = Program.objects.get(id=program_id)
                if study_year > program.duration_years:
                    raise serializers.ValidationError({
                        "current_study_year": _(
                            f"Study year cannot exceed program duration of "
                            f"{program.duration_years} years."
                        )
                    })
            except Program.DoesNotExist:
                pass

        return data

    def create(self, validated_data):
        """Create student instance."""
        user_id = validated_data.pop("user_id")
        department_id = validated_data.pop("department_id")
        program_id = validated_data.pop("program_id")

        from apps.accounts.models import User
        from apps.departments.models import Department
        from apps.programs.models import Program

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise serializers.ValidationError({"user": _("User not found.")})

        try:
            department = Department.objects.get(id=department_id)
        except Department.DoesNotExist:
            raise serializers.ValidationError(
                {"department": _("Department not found.")}
            )

        try:
            program = Program.objects.get(id=program_id)
        except Program.DoesNotExist:
            raise serializers.ValidationError(
                {"program": _("Program not found.")}
            )

        return Student.objects.create(
            user=user,
            department=department,
            program=program,
            **validated_data
        )

    def update(self, instance, validated_data):
        """Update student instance."""
        user_id = validated_data.pop("user_id", None)
        department_id = validated_data.pop("department_id", None)
        program_id = validated_data.pop("program_id", None)

        if user_id:
            raise serializers.ValidationError(
                {"user": _("Cannot change user association.")}
            )

        if program_id and program_id != instance.program_id:
            raise serializers.ValidationError(
                {"program": _("Cannot change program association.")}
            )

        if department_id and department_id != instance.department_id:
            raise serializers.ValidationError(
                {"department": _("Cannot change department association.")}
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class AcademicProgressSerializer(serializers.ModelSerializer):
    """Serializer for academic progress records."""

    status_display = serializers.CharField(
        source="get_academic_status_display",
        read_only=True,
    )
    student_registration = serializers.CharField(
        source="student.registration_number",
        read_only=True,
    )
    recorded_by_name = serializers.CharField(
        source="recorded_by.get_full_name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = AcademicProgress
        fields = [
            "id",
            "student_registration",
            "academic_year",
            "study_year",
            "semester",
            "gpa",
            "cgpa",
            "total_credits",
            "credits_this_semester",
            "academic_status",
            "status_display",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]


class StudentEnrollmentSerializer(serializers.ModelSerializer):
    """Serializer for student enrollment records."""

    status_display = serializers.CharField(
        source="get_enrollment_status_display",
        read_only=True,
    )
    student_registration = serializers.CharField(
        source="student.registration_number",
        read_only=True,
    )
    curriculum_info = serializers.SerializerMethodField()

    class Meta:
        model = StudentEnrollment
        fields = [
            "id",
            "student_registration",
            "curriculum_info",
            "academic_year",
            "study_year",
            "semester",
            "enrollment_status",
            "status_display",
            "enrollment_date",
            "notes",
        ]
        read_only_fields = [
            "id",
            "enrollment_date",
        ]

    def get_curriculum_info(self, obj):
        """Get curriculum information."""
        return {
            "id": str(obj.curriculum.id),
            "program": obj.curriculum.program.code,
            "academic_year": obj.curriculum.academic_year,
        }


class StudentProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for students to update their own profile.
    Restricts which fields can be updated.
    """

    class Meta:
        model = Student
        fields = [
            "first_name",
            "last_name",
            "phone_number",
            "date_of_birth",
            "profile_photo",
        ]

    def validate_phone_number(self, value):
        """Validate phone number format."""
        import re
        if value and not re.match(r"^\+?1?\d{9,15}$", value):
            raise serializers.ValidationError(
                _("Phone number must be valid international format.")
            )
        return value


class StudentMyProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for logged-in student viewing their own profile.
    Includes personal and academic information.
    """

    user = UserSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    program = ProgramSerializer(read_only=True)
    gender_display = serializers.CharField(
        source="get_gender_display",
        read_only=True,
    )
    academic_status_display = serializers.CharField(
        source="get_academic_status_display",
        read_only=True,
    )
    full_name = serializers.SerializerMethodField()
    academic_year_string = serializers.CharField(read_only=True, source="academic_year_string")

    class Meta:
        model = Student
        fields = [
            "id",
            "registration_number",
            "user",
            "first_name",
            "last_name",
            "full_name",
            "gender",
            "gender_display",
            "email",
            "phone_number",
            "date_of_birth",
            "department",
            "program",
            "current_study_year",
            "current_semester",
            "admission_year",
            "academic_status",
            "academic_status_display",
            "academic_year_string",
            "profile_photo",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

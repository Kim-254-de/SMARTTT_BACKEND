from rest_framework import serializers
from apps.accounts.models import User


class UserProfileSerializer(serializers.ModelSerializer):
    # Add writeable fields for student preferences so the serializer accepts them
    timetable_group = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    combination = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    year_of_study = serializers.IntegerField(required=False, source="student_profile.current_study_year")
    program_id = serializers.UUIDField(required=False, write_only=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "university_id",
            "phone_number",
            "timetable_group",
            "combination",
            "year_of_study",
            "program_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "username",
            "role",
            "university_id",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Expose student-specific profile fields if the user is a student
        if hasattr(instance, "student_profile") and instance.student_profile:
            student = instance.student_profile
            data["timetable_group"] = student.timetable_group
            data["combination"] = student.combination
            data["year_of_study"] = student.current_study_year
            data["program_id"] = str(student.program_id) if student.program_id else None
        return data

    def update(self, instance, validated_data):
        # Extract student-specific fields
        timetable_group = validated_data.pop("timetable_group", None)
        combination = validated_data.pop("combination", None)
        program_id = validated_data.pop("program_id", None)
        
        # Handle year_of_study mapped via source/nested extraction
        student_data = validated_data.pop("student_profile", {})
        year_of_study = student_data.get("current_study_year")

        # Update standard User fields
        user = super().update(instance, validated_data)

        # Update associated Student profile if it exists
        if hasattr(user, "student_profile") and user.student_profile:
            student = user.student_profile
            if timetable_group is not None:
                student.timetable_group = timetable_group
            if combination is not None:
                student.combination = combination
            if year_of_study is not None:
                student.current_study_year = year_of_study
            if program_id is not None:
                student.program_id = program_id
            student.save()

        return user

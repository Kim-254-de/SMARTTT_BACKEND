from rest_framework import serializers
from .models import Department, Faculty, Lecturer, Program, Room


class FacultySerializer(serializers.ModelSerializer):
    class Meta:
        model = Faculty
        fields = ["id", "name", "code"]


class DepartmentSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.name", read_only=True)

    class Meta:
        model = Department
        fields = ["id", "faculty", "faculty_name", "name", "code"]


class ProgramSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Program
        fields = ["id", "department", "department_name", "name", "code", "duration_years"]


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["id", "code", "name", "building", "capacity", "room_type"]


class LecturerSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Lecturer
        fields = ["id", "full_name", "department", "department_name", "title"]

    def get_full_name(self, obj):
        return obj.user.get_full_name()

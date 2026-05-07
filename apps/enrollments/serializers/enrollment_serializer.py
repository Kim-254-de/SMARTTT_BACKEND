from rest_framework import serializers

from apps.enrollments.models import StudentEnrollment


class StudentEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentEnrollment
        fields = "__all__"

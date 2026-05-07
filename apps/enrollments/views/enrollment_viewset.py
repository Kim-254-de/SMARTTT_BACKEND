from rest_framework.viewsets import ModelViewSet

from apps.enrollments.models import StudentEnrollment
from apps.enrollments.serializers import StudentEnrollmentSerializer


class StudentEnrollmentViewSet(ModelViewSet):
    queryset = StudentEnrollment.objects.select_related("student", "curriculum_unit", "term").all()
    serializer_class = StudentEnrollmentSerializer
    filterset_fields = ["term", "status", "student"]

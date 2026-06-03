from rest_framework.viewsets import ModelViewSet

from apps.students.models import Student
from apps.students.serializers import StudentSerializer


class StudentViewSet(ModelViewSet):
    queryset = Student.objects.select_related("user", "program", "program__department").all()
    serializer_class = StudentSerializer
    filterset_fields = ["program", "academic_status", "admission_year", "current_study_year"]
    search_fields = ["user__first_name", "user__last_name", "user__university_id"]

from rest_framework.viewsets import ModelViewSet

from apps.lecturers.models import Lecturer
from apps.lecturers.serializers import LecturerSerializer


class LecturerViewSet(ModelViewSet):
    queryset = Lecturer.objects.select_related("user", "department").all()
    serializer_class = LecturerSerializer
    filterset_fields = ["department", "rank"]
    search_fields = ["user__first_name", "user__last_name", "user__university_id"]

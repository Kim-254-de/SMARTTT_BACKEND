from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.programs.models import Program
from apps.programs.serializers import ProgramSerializer


class ProgramViewSet(ModelViewSet):
    queryset = Program.objects.select_related("department").all()
    serializer_class = ProgramSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["department", "duration_years"]
    search_fields = ["name", "code", "department__name", "department__code"]

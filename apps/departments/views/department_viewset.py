from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.departments.models import Department
from apps.departments.serializers import DepartmentSerializer


class DepartmentViewSet(ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAdminOrReadOnly]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]

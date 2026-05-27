from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.units.models import Unit
from apps.units.serializers import UnitSerializer


class UnitViewSet(ModelViewSet):
    queryset = Unit.objects.select_related("department").all()
    serializer_class = UnitSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["department", "credit_hours"]
    search_fields = ["name", "code", "department__name"]

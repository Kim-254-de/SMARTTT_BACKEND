from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.curriculum.serializers import CurriculumSerializer, CurriculumUnitSerializer


class CurriculumViewSet(ModelViewSet):
    queryset = Curriculum.objects.select_related("program", "program__department").all()
    serializer_class = CurriculumSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["program", "is_active"]


class CurriculumUnitViewSet(ModelViewSet):
    queryset = CurriculumUnit.objects.select_related("curriculum", "unit").all()
    serializer_class = CurriculumUnitSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["curriculum", "year_of_study", "semester", "is_core"]

from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.analytics.models import TimetableMetric
from apps.analytics.serializers import TimetableMetricSerializer


class TimetableMetricViewSet(ReadOnlyModelViewSet):
    queryset = TimetableMetric.objects.all()
    serializer_class = TimetableMetricSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["metric_date", "key"]

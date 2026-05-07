from rest_framework import serializers

from apps.analytics.models import TimetableMetric


class TimetableMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableMetric
        fields = "__all__"

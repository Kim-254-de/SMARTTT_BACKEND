from django.db import models

from apps.common.models import BaseModel


class TimetableMetric(BaseModel):
    metric_date = models.DateField()
    key = models.CharField(max_length=100)
    value = models.FloatField()
    dimensions = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-metric_date", "key"]

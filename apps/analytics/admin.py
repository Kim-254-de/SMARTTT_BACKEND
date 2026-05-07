from django.contrib import admin

from .models import TimetableMetric


@admin.register(TimetableMetric)
class TimetableMetricAdmin(admin.ModelAdmin):
	list_display = ("metric_date", "key", "value")
	list_filter = ("metric_date", "key")

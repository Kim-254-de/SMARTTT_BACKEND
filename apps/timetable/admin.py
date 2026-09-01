from django.contrib import admin
from .models import AcademicTerm, TimetableSlot
from .utils.day_order import day_of_week_sort_case


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ["academic_year", "semester", "is_current", "start_date", "end_date"]

@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ["unit", "program", "year_of_study", "day_of_week", "start_time", "end_time", "room", "term"]
    list_filter = ["term", "day_of_week", "program"]
    search_fields = ["unit__code", "unit__name"]

    def get_queryset(self, request):
        # day_of_week is a short string ('mon','tue',...) so the default
        # alphabetical ordering shows Friday's slots before Monday's -
        # sort by real calendar day order instead.
        qs = super().get_queryset(request)
        return qs.annotate(_day_sort=day_of_week_sort_case()).order_by("_day_sort", "start_time")

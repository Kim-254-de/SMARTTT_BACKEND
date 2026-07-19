from django.contrib import admin
from .models import AcademicTerm, TimetableSlot


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ["academic_year", "semester", "is_current", "start_date", "end_date"]

@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ["unit", "program", "year_of_study", "day", "start_time", "end_time", "room", "term"]
    list_filter = ["term", "day", "program"]
    search_fields = ["unit__code", "unit__name"]

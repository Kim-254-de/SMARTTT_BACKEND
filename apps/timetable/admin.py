from django.contrib import admin
from .models import AcademicTerm, TimetableSlot, TimetableUpload, Unit

@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ["academic_year", "semester", "is_current", "start_date", "end_date"]

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "department", "credit_hours"]
    search_fields = ["code", "name"]
    list_filter = ["department"]

@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ["unit", "program", "year_of_study", "day", "start_time", "end_time", "room", "term"]
    list_filter = ["term", "day", "program"]
    search_fields = ["unit__code", "unit__name"]

@admin.register(TimetableUpload)
class TimetableUploadAdmin(admin.ModelAdmin):
    list_display = ["uploaded_by", "status", "rows_received", "rows_saved", "rows_failed", "uploaded_at"]
    readonly_fields = ["errors"]

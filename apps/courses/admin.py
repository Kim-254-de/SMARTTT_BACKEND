from django.contrib import admin
from .models import StudentUnit

@admin.register(StudentUnit)
class StudentUnitAdmin(admin.ModelAdmin):
    list_display = ["user", "unit", "term", "synced_at"]
    list_filter = ["term"]
    search_fields = ["user__university_id", "unit__code"]

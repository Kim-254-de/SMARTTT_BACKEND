from django.contrib import admin

from .models import Program


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
	list_display = ("code", "name", "department", "duration_years")
	list_filter = ("department",)
	search_fields = ("code", "name")

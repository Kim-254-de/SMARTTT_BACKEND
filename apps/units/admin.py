from django.contrib import admin

from .models import Unit


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
	list_display = ("code", "title", "department", "credit_hours")
	list_filter = ("department",)
	search_fields = ("code", "title")

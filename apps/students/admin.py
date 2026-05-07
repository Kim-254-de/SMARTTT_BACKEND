from django.contrib import admin

from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
	list_display = ("user", "program", "admission_year", "current_year", "status")
	list_filter = ("program", "status")
	search_fields = ("user__first_name", "user__last_name", "user__university_id")

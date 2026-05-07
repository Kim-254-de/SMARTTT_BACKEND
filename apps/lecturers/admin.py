from django.contrib import admin

from .models import Lecturer


@admin.register(Lecturer)
class LecturerAdmin(admin.ModelAdmin):
	list_display = ("user", "department", "rank", "max_weekly_teaching_hours")
	list_filter = ("department",)
	search_fields = ("user__first_name", "user__last_name", "user__university_id")

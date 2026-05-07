from django.contrib import admin

from .models import StudentEnrollment


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
	list_display = ("student", "curriculum_unit", "term", "status", "score")
	list_filter = ("term", "status")

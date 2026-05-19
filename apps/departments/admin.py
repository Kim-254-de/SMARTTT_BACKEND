from django.contrib import admin
from apps.departments.models import Faculty, Department, DepartmentAdmin


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code")
    search_fields = ("name", "code")


@admin.register(Department)
class DepartmentAdminModel(admin.ModelAdmin):
    list_display = ("id", "name", "code", "faculty", "status")
    list_filter = ("faculty", "status")
    search_fields = ("name", "code")


@admin.register(DepartmentAdmin)
class DepartmentAdminAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "department", "role", "assigned_at")
    list_filter = ("role",)

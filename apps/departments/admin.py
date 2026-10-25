from django.contrib import admin
from apps.departments.models import Department, DepartmentAdmin

@admin.register(Department)
class DepartmentAdminModel(admin.ModelAdmin):
    list_display = ("id", "name", "code", "status")
    list_filter = ("status",)
    search_fields = ("name", "code")

@admin.register(DepartmentAdmin)
class DepartmentAdminAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "department", "role", "assigned_at")
    list_filter = ("role",)

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import PasswordResetToken, User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ["email", "university_id", "role", "is_active"]
    list_filter = ["role", "is_active"]
    fieldsets = UserAdmin.fieldsets + (
        ("SMARTTT", {"fields": ("role", "university_id", "phone_number")}),
    )


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "expires_at", "is_used", "created_at"]
    search_fields = ["user__email", "token"]
    list_filter = ["is_used", "created_at"]

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Admin for Room model."""

    list_display = (
        "code",
        "name",
        "building",
        "floor",
        "capacity",
        "room_type_display",
        "status_badge",
        "sessions_count",
    )
    list_filter = ("building", "room_type", "status", "capacity", "created_at")
    search_fields = ("code", "name", "building")
    readonly_fields = ("id", "sessions_count_readonly", "created_at", "updated_at")
    ordering = ("building", "floor", "code")

    fieldsets = (
        (
            _("Room Information"),
            {
                "fields": ("id", "code", "name", "building", "floor", "capacity", "room_type")
            },
        ),
        (
            _("Status & Details"),
            {
                "fields": ("status", "description", "facilities"),
            },
        ),
        (
            _("Statistics"),
            {
                "fields": ("sessions_count_readonly",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def room_type_display(self, obj):
        return obj.get_room_type_display()

    room_type_display.short_description = _("Type")

    def status_badge(self, obj):
        colors = {
            "active": "green",
            "maintenance": "orange",
            "closed": "red",
            "unavailable": "gray",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = _("Status")

    def sessions_count(self, obj):
        count = obj.timetable_sessions.filter(status__in=["scheduled", "active"]).count()
        return count

    sessions_count.short_description = _("Active Sessions")

    def sessions_count_readonly(self, obj):
        return obj.timetable_sessions.count()

    sessions_count_readonly.short_description = _("Total Sessions")

    actions = ["mark_active", "mark_maintenance", "mark_closed"]

    def mark_active(self, request, queryset):
        updated = queryset.update(status="active")
        self.message_user(request, f"{updated} rooms marked as active")

    mark_active.short_description = _("Mark selected as Active")

    def mark_maintenance(self, request, queryset):
        updated = queryset.update(status="maintenance")
        self.message_user(request, f"{updated} rooms marked as Under Maintenance")

    mark_maintenance.short_description = _("Mark selected as Under Maintenance")

    def mark_closed(self, request, queryset):
        updated = queryset.update(status="closed")
        self.message_user(request, f"{updated} rooms marked as Closed")

    mark_closed.short_description = _("Mark selected as Closed")


"""
Admin configuration for timetable app.

Production-level admin interface for:
- Time slot management
- Timetable session management with conflict detection
- Academic terms
- Timetable uploads
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, F, Q
from django.utils.translation import gettext_lazy as _

from apps.timetable.models import TimeSlot, TimetableSession, AcademicTerm, TimetableConflict, TimetableSlot, TimetableUploadBatch


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    """Admin for TimeSlot model."""

    list_display = (
        "slot_name",
        "time_range",
        "duration_minutes",
        "status_badge",
        "sessions_count",
    )
    list_filter = ("status", "start_time", "created_at")
    search_fields = ("slot_name", "description")
    readonly_fields = ("id", "duration_minutes", "sessions_count_readonly", "created_at", "updated_at")
    ordering = ("start_time",)

    fieldsets = (
        (
            _("Time Slot Information"),
            {
                "fields": ("id", "slot_name", "start_time", "end_time", "duration_minutes")
            },
        ),
        (
            _("Status & Details"),
            {
                "fields": ("status", "description"),
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

    def time_range(self, obj):
        return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"

    time_range.short_description = _("Time Range")

    def status_badge(self, obj):
        color = "green" if obj.status == "active" else "gray"
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = _("Status")

    def sessions_count(self, obj):
        return obj.timetable_sessions.filter(status__in=["scheduled", "active"]).count()

    sessions_count.short_description = _("Active Sessions")

    def sessions_count_readonly(self, obj):
        return obj.timetable_sessions.count()

    sessions_count_readonly.short_description = _("Total Sessions")


@admin.register(TimetableSession)
class TimetableSessionAdmin(admin.ModelAdmin):
    """Admin for TimetableSession model."""

    list_display = (
        "unit_code",
        "program_short",
        "day_display",
        "time_display",
        "room_code",
        "lecturer_name",
        "occupancy_display",
        "status_badge",
    )
    list_filter = (
        "status",
        "day_of_week",
        "semester",
        "study_year",
        "session_type",
        "delivery_mode",
        "academic_year",
        "department",
        "program",
        "created_at",
    )
    search_fields = (
        "unit__code",
        "unit__title",
        "program__name",
        "room__code",
        "lecturer__user__last_name",
    )
    readonly_fields = (
        "id",
        "occupancy_percentage",
        "available_seats",
        "is_full",
        "created_by_display",
        "created_at",
        "updated_at",
    )
    ordering = ("day_of_week", "time_slot__start_time")

    fieldsets = (
        (
            _("Academic Context"),
            {
                "fields": ("unit", "program", "department", "academic_year", "study_year", "semester")
            },
        ),
        (
            _("Scheduling"),
            {
                "fields": (
                    "day_of_week",
                    "time_slot",
                    "session_type",
                    "delivery_mode",
                    "student_group",
                )
            },
        ),
        (
            _("Resources"),
            {
                "fields": ("lecturer", "room"),
            },
        ),
        (
            _("Enrollment"),
            {
                "fields": ("max_students", "current_enrollment", "occupancy_percentage", "available_seats", "is_full"),
            },
        ),
        (
            _("Status & Notes"),
            {
                "fields": ("status", "notes", "created_by_display"),
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

    def unit_code(self, obj):
        return obj.unit.code

    unit_code.short_description = _("Unit")

    def program_short(self, obj):
        return obj.program.code

    program_short.short_description = _("Program")

    def day_display(self, obj):
        return obj.get_day_display()

    day_display.short_description = _("Day")

    def time_display(self, obj):
        return obj.get_session_time_str()

    time_display.short_description = _("Time")

    def room_code(self, obj):
        return obj.room.code if obj.room else "TBA"

    room_code.short_description = _("Room")

    def lecturer_name(self, obj):
        return obj.lecturer.user.get_full_name() if obj.lecturer else "TBA"

    lecturer_name.short_description = _("Lecturer")

    def occupancy_display(self, obj):
        percentage = obj.occupancy_percentage
        color = "red" if percentage >= 90 else "orange" if percentage >= 70 else "green"
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{:.0f}%</span>',
            color,
            percentage,
        )

    occupancy_display.short_description = _("Occupancy")

    def status_badge(self, obj):
        colors = {
            "scheduled": "blue",
            "active": "green",
            "completed": "gray",
            "cancelled": "red",
            "suspended": "orange",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = _("Status")

    def created_by_display(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else "System"

    created_by_display.short_description = _("Created By")

    actions = ["activate_sessions", "complete_sessions", "cancel_sessions"]

    def activate_sessions(self, request, queryset):
        updated = queryset.filter(status="scheduled").update(status="active")
        self.message_user(request, f"{updated} sessions activated")

    activate_sessions.short_description = _("Activate selected sessions")

    def complete_sessions(self, request, queryset):
        updated = queryset.filter(status__in=["scheduled", "active"]).update(status="completed")
        self.message_user(request, f"{updated} sessions marked as completed")

    complete_sessions.short_description = _("Mark selected as completed")

    def cancel_sessions(self, request, queryset):
        updated = queryset.filter(status__in=["scheduled", "active"]).update(status="cancelled")
        self.message_user(request, f"{updated} sessions cancelled")

    cancel_sessions.short_description = _("Cancel selected sessions")
>>>>>>> ee31cab66c0474900ecd8694bbe0aa38c2c4fc1b


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ("id", "academic_year", "semester", "start_date", "end_date", "is_current")
    list_filter = ("is_current", "academic_year", "semester")
    search_fields = ("academic_year",)


@admin.register(TimetableUploadBatch)
class TimetableUploadBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "rows_received", "rows_saved", "created_at")
    list_filter = ("status", "created_at")
<<<<<<< HEAD
    search_fields = ("status",)
=======
    search_fields = ("uploaded_by__user__last_name", "id")
    readonly_fields = ("id", "source_file", "created_at", "updated_at")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            _("Upload Information"),
            {
                "fields": ("id", "uploaded_by", "source_file", "status")
            },
        ),
        (
            _("Processing"),
            {
                "fields": ("rows_received", "rows_saved", "validation_errors"),
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

    def id_short(self, obj):
        return str(obj.id)[:8]

    id_short.short_description = _("ID")

    def uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name()

    uploaded_by_name.short_description = _("Uploaded By")

    def status_badge(self, obj):
        colors = {
            "received": "blue",
            "validated": "orange",
            "processed": "green",
            "failed": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = _("Status")

    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    created_at_short.short_description = _("Uploaded")
>>>>>>> ee31cab66c0474900ecd8694bbe0aa38c2c4fc1b


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "term",
        "curriculum_unit",
        "lecturer",
        "room",
        "day_of_week",
        "start_time",
        "end_time",
    )
    list_filter = ("term", "day_of_week", "room")
    search_fields = (
<<<<<<< HEAD
        "curriculum_unit__unit__code",
        "curriculum_unit__unit__name",
        "room__code",
        "room__building",
        "lecturer__user__university_id",
=======
        "unit__code",
>>>>>>> ee31cab66c0474900ecd8694bbe0aa38c2c4fc1b
        "lecturer__user__first_name",
        "lecturer__user__last_name",
        "class_group",
    )
<<<<<<< HEAD
=======
    ordering = ("term", "day_of_week", "start_time")
    readonly_fields = ("id", "created_at", "updated_at", "conflict_count")
    date_hierarchy = "created_at"
    
    fieldsets = (
        ("Session Details", {
            "fields": (
                "term",
                "unit",
                "program",
                "year_of_study",
                "class_group"
            )
        }),
        ("Schedule", {
            "fields": (
                "day_of_week",
                "start_time",
                "end_time"
            )
        }),
        ("Resources", {
            "fields": (
                "lecturer",
                "room"
            )
        }),
        ("Upload Tracking", {
            "fields": ("upload_batch",),
            "classes": ("collapse",)
        }),
        ("Conflicts", {
            "fields": ("conflict_count",),
            "classes": ("collapse",)
        }),
        ("Timestamps", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def get_unit_code(self, obj):
        """Display unit code from related unit."""
        return obj.unit.code
    get_unit_code.short_description = "Unit"
    get_unit_code.admin_order_field = "unit__code"
    
    def get_lecturer_name(self, obj):
        """Display lecturer's full name."""
        return obj.lecturer.user.get_full_name()
    get_lecturer_name.short_description = "Lecturer"
    get_lecturer_name.admin_order_field = "lecturer__user__first_name"
    
    def time_slot(self, obj):
        """Display formatted time slot."""
        return f"{obj.start_time} - {obj.end_time}"
    time_slot.short_description = "Time"
    
    def conflict_count(self, obj):
        """Display count of conflicts involving this slot."""
        count = TimetableConflict.objects.filter(
            Q(slot_a=obj) | Q(slot_b=obj)
        ).count()
        
        if count == 0:
            return format_html(
                '<span style="color: #198754;">No conflicts</span>'
            )
        else:
            return format_html(
                f'<span style="color: #dc3545; font-weight: bold;">{count} conflicts</span>'
            )
    conflict_count.short_description = "Conflict Status"
    
    def conflict_status(self, obj):
        """Display conflict status badge."""
        conflicts = TimetableConflict.objects.filter(
            Q(slot_a=obj) | Q(slot_b=obj)
        ).count()
        
        if conflicts == 0:
            return format_html(
                '<span style="background-color: #198754; color: white; '
                'padding: 3px 8px; border-radius: 3px;">✓ OK</span>'
            )
        else:
            return format_html(
                f'<span style="background-color: #dc3545; color: white; '
                f'padding: 3px 8px; border-radius: 3px;">⚠ {conflicts}</span>'
            )
    conflict_status.short_description = "Status"
>>>>>>> ee31cab66c0474900ecd8694bbe0aa38c2c4fc1b


@admin.register(TimetableConflict)
class TimetableConflictAdmin(admin.ModelAdmin):
<<<<<<< HEAD
    list_display = ("id", "conflict_type", "term", "created_at")
    list_filter = ("conflict_type", "term")
    search_fields = ("conflict_type",)
=======
    """Admin for TimetableConflict model."""
    
    list_display = (
        "id",
        "conflict_type_badge",
        "term",
        "slot_a_info",
        "slot_b_info",
        "created_at"
    )
    list_filter = ("conflict_type", "term", "created_at")
    search_fields = (
        "slot_a__unit__code",
        "slot_b__unit__code",
        "slot_a__room__code",
        "slot_b__room__code"
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "formatted_details"
    )
    date_hierarchy = "created_at"
    
    fieldsets = (
        ("Conflict Information", {
            "fields": ("conflict_type", "term")
        }),
        ("Conflicting Slots", {
            "fields": ("slot_a", "slot_b")
        }),
        ("Details", {
            "fields": ("formatted_details",),
        }),
        ("Timestamps", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def conflict_type_badge(self, obj):
        """Display conflict type as color-coded badge."""
        colors = {
            "room": "#0d6efd",
            "lecturer": "#ffc107",
            "program": "#dc3545"
        }
        icons = {
            "room": "🏛",
            "lecturer": "👨‍🏫",
            "program": "📚"
        }
        color = colors.get(obj.conflict_type, "#6c757d")
        icon = icons.get(obj.conflict_type, "")
        
        return format_html(
            f'<span style="background-color: {color}; color: white; '
            f'padding: 5px 10px; border-radius: 3px; font-weight: bold;">'
            f'{icon} {obj.get_conflict_type_display()}</span>'
        )
    conflict_type_badge.short_description = "Type"
    
    def slot_a_info(self, obj):
        """Display info about first conflicting slot."""
        return f"{obj.slot_a.unit.code} {obj.slot_a.get_day_of_week_display()}"
    slot_a_info.short_description = "Slot A"
    
    def slot_b_info(self, obj):
        """Display info about second conflicting slot."""
        return f"{obj.slot_b.unit.code} {obj.slot_b.get_day_of_week_display()}"
    slot_b_info.short_description = "Slot B"
    
    def formatted_details(self, obj):
        """Display conflict details as formatted HTML."""
        if not obj.details:
            return "No details"
        
        try:
            details = obj.details
            html = "<dl style='margin: 0;'>"
            
            for key, value in details.items():
                if isinstance(value, dict):
                    html += f"<dt><strong>{key}:</strong></dt><dd>"
                    for k, v in value.items():
                        html += f"<div>{k}: {v}</div>"
                    html += "</dd>"
                else:
                    html += f"<dt><strong>{key}:</strong></dt><dd>{value}</dd>"
            
            html += "</dl>"
            return format_html(html)
        except Exception as e:
            return f"Error displaying details: {str(e)}"
    formatted_details.short_description = "Conflict Details"
>>>>>>> ee31cab66c0474900ecd8694bbe0aa38c2c4fc1b

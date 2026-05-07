from django.contrib import admin

from .models import AcademicTerm, TimetableConflict, TimetableSlot, TimetableUploadBatch


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
	list_display = ("academic_year", "semester", "is_current")
	list_filter = ("academic_year", "semester", "is_current")


@admin.register(TimetableUploadBatch)
class TimetableUploadBatchAdmin(admin.ModelAdmin):
	list_display = ("id", "uploaded_by", "status", "rows_received", "rows_saved", "created_at")
	list_filter = ("status", "created_at")


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
	list_display = ("term", "curriculum_unit", "lecturer", "room", "day_of_week", "start_time", "end_time")
	list_filter = ("term", "day_of_week", "room")


@admin.register(TimetableConflict)
class TimetableConflictAdmin(admin.ModelAdmin):
	list_display = ("conflict_type", "term", "slot_a", "slot_b", "created_at")
	list_filter = ("conflict_type", "term")

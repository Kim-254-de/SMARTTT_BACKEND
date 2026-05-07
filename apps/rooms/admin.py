from django.contrib import admin

from .models import Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
	list_display = ("code", "building", "capacity", "room_type")
	list_filter = ("building", "room_type")
	search_fields = ("code", "building")

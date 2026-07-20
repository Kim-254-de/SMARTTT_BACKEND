from django.contrib import admin
from .models import Department, Faculty, Lecturer, Program, Room

admin.site.register(Faculty)
admin.site.register(Department)
admin.site.register(Program)
admin.site.register(Room)
admin.site.register(Lecturer)

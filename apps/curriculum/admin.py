from django.contrib import admin

from .models import Curriculum, CurriculumUnit


@admin.register(Curriculum)
class CurriculumAdmin(admin.ModelAdmin):
	list_display = ("program", "version_name", "effective_academic_year", "is_active")
	list_filter = ("program", "is_active")


@admin.register(CurriculumUnit)
class CurriculumUnitAdmin(admin.ModelAdmin):
	list_display = ("curriculum", "unit", "year_of_study", "semester", "is_core")
	list_filter = ("curriculum", "year_of_study", "semester")

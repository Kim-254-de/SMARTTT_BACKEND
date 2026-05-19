from django.contrib import admin

from .models import Curriculum, CurriculumUnit, CurriculumVersion


class CurriculumUnitInline(admin.TabularInline):
    model = CurriculumUnit
    extra = 1
    autocomplete_fields = ("unit", "prerequisite_unit")


class CurriculumVersionInline(admin.TabularInline):
    model = CurriculumVersion
    extra = 0
    can_delete = False
    readonly_fields = ("version", "action", "change_summary", "acted_by", "created_at")


@admin.register(Curriculum)
class CurriculumAdmin(admin.ModelAdmin):
    list_display = (
        "program",
        "department",
        "academic_year",
        "study_year",
        "semester",
        "version",
        "status",
    )
    list_filter = ("department", "program", "academic_year", "study_year", "semester", "status")
    search_fields = ("program__code", "program__name", "department__code", "department__name")
    autocomplete_fields = ("program", "department", "created_by")
    inlines = (CurriculumUnitInline, CurriculumVersionInline)


@admin.register(CurriculumUnit)
class CurriculumUnitAdmin(admin.ModelAdmin):
    list_display = (
        "curriculum",
        "unit",
        "display_order",
        "is_core",
        "is_elective",
        "credit_hours",
    )
    list_filter = ("curriculum", "is_core", "is_elective")
    autocomplete_fields = ("curriculum", "unit", "prerequisite_unit")


@admin.register(CurriculumVersion)
class CurriculumVersionAdmin(admin.ModelAdmin):
    list_display = ("curriculum", "version", "action", "acted_by", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("curriculum__program__code", "curriculum__academic_year")

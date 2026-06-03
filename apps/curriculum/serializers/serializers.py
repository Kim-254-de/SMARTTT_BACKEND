from rest_framework import serializers
from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.units.models import Unit
from apps.units.serializers.serializers import UnitSerializer
from apps.units.models import Unit


class CurriculumUnitSerializer(serializers.ModelSerializer):
    unit = UnitSerializer(read_only=True)
    unit_id = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.all(), source="unit", write_only=True)

    class Meta:
        model = CurriculumUnit
        fields = ("id", "curriculum", "unit", "unit_id", "is_core", "is_elective", "display_order", "prerequisite_unit", "credit_hours")


class CurriculumSerializer(serializers.ModelSerializer):
    units = CurriculumUnitSerializer(many=True, read_only=True)

    class Meta:
        model = Curriculum
        fields = ("id", "program", "academic_year", "study_year", "semester", "version", "status", "created_by", "created_at", "units")
        read_only_fields = ("created_at",)

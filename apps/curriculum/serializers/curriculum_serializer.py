from rest_framework import serializers

from apps.curriculum.models import Curriculum, CurriculumUnit


class CurriculumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Curriculum
        fields = "__all__"


class CurriculumUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurriculumUnit
        fields = "__all__"

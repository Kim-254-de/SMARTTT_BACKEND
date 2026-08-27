from rest_framework import serializers

from apps.units.models import Unit


class UnitSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Unit
        fields = [
            "id",
            "title",
            "code",
            "credit_hours",
            "department",
            "department_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "department_name", "created_at", "updated_at"]

from rest_framework import serializers

from apps.accounts.models import User


class LanguageUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["preferred_language"]

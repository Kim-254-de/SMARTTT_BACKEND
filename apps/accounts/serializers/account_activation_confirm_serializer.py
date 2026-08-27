from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import serializers

from apps.accounts.models import User


class AccountActivationConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)
    uid = serializers.IntegerField(required=True)

    def validate(self, data):
        """Validate token and uid, then activate account."""
        try:
            user = User.objects.get(id=data["uid"])
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"uid": "Invalid user ID."}
            )

        # Verify token is valid
        token_generator = PasswordResetTokenGenerator()
        if not token_generator.check_token(user, data["token"]):
            raise serializers.ValidationError(
                {"token": "Invalid or expired activation token."}
            )

        if user.is_active:
            raise serializers.ValidationError(
                {"detail": "Account is already activated."}
            )

        # Store user for save()
        self.user = user
        return data

    def save(self):
        """Activate the user account."""
        self.user.is_active = True
        self.user.save()
        return self.user

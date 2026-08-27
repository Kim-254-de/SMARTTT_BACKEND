from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import serializers

from apps.accounts.models import User


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)
    uid = serializers.IntegerField(required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        """Validate token, uid, and password match."""
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
                {"token": "Invalid or expired token."}
            )

        # Ensure passwords match
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )

        # Validate password strength
        try:
            validate_password(data["new_password"], user=user)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"new_password": e.messages})

        # Store user for save()
        self.user = user
        return data

    def save(self):
        """Reset the user's password."""
        self.user.set_password(self.validated_data["new_password"])
        self.user.save()
        return self.user

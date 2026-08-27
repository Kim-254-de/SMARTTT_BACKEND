from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import serializers

from apps.accounts.models import User


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        """Check if user with this email exists."""
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "No user found with this email address."
            )
        return value

    def save(self):
        """Generate a password reset token for the user."""
        email = self.validated_data["email"]
        user = User.objects.get(email=email)
        token_generator = PasswordResetTokenGenerator()
        token = token_generator.make_token(user)
        
        # Return user and token (for development; in production, send via email)
        return {"user": user, "token": token}

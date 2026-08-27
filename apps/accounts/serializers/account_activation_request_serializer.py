from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import serializers

from apps.accounts.models import User


class AccountActivationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        """Check if user with this email exists and is inactive."""
        try:
            self.user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user found with this email address.")
        
        if self.user.is_active:
            raise serializers.ValidationError("Account is already activated.")
        
        return value

    def save(self):
        """Generate activation token."""
        token_generator = PasswordResetTokenGenerator()
        token = token_generator.make_token(self.user)
        
        # TODO: In production, send activation link via email:
        # activation_link = f"https://frontend.com/activate?uid={self.user.id}&token={token}"
        # send_activation_email(self.user.email, activation_link)
        
        return {"user": self.user, "token": token}

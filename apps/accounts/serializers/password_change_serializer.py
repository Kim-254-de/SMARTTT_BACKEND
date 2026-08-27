from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate_old_password(self, value):
        """Verify the old password is correct."""
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, data):
        """Ensure new password and confirm password match."""
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )

        # Validate password strength using Django's validators
        try:
            validate_password(data["new_password"], user=self.context["request"].user)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"new_password": e.detail})

        return data

    def save(self):
        """Update the user's password."""
        user = self.context["request"].user

        data = getattr(self, "validated_data", None)
        new_password = data.get("new_password") if isinstance(data, dict) else None
        if not new_password:
            raise serializers.ValidationError({"new_password": "New password is required."})

        user.set_password(new_password)
        user.save()
        return user

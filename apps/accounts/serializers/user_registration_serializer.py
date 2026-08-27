from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User

SCHOOL_EMAIL_DOMAIN = "tharaka.ac.ke"


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "confirm_password",
            "role",
            "university_id",
            "phone_number",
        ]
        extra_kwargs = {
            "first_name": {"required": True},
            "last_name": {"required": True},
            "role": {"required": True},
            "university_id": {"required": True},
        }

    def validate_username(self, value):
        """Check if username is unique."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists.")
        return value

    def validate_email(self, value):
        """Validate email is from school domain and is unique."""
        if not value.endswith(f"@{SCHOOL_EMAIL_DOMAIN}"):
            raise serializers.ValidationError(
                f"Email must be from school domain (@{SCHOOL_EMAIL_DOMAIN})."
            )
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def validate_university_id(self, value):
        """Check if university_id is unique."""
        if User.objects.filter(university_id=value).exists():
            raise serializers.ValidationError("University ID already registered.")
        return value

    def validate_role(self, value):
        """Restrict registration to student and lecturer roles only."""
        allowed_roles = [User.Role.STUDENT, User.Role.LECTURER]
        if value not in allowed_roles:
            raise serializers.ValidationError(
                f"Registration allowed for roles: {', '.join(allowed_roles)}"
            )
        return value

    def validate(self, data):
        """Validate password strength and confirmation."""
        password = data.get("password")
        confirm_password = data.pop("confirm_password")

        if password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )

        # Validate password strength
        try:
            # Create a temporary user object for validation context
            user = User(**{k: v for k, v in data.items() if k != "password"})
            validate_password(password, user=user)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"password": e.messages})

        return data

    def create(self, validated_data):
        """Create a new inactive user (requires email verification)."""
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            role=validated_data["role"],
            university_id=validated_data["university_id"],
            phone_number=validated_data.get("phone_number", ""),
            is_active=False,  # Require email verification
        )
        return user

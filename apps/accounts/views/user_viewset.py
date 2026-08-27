from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import User
from apps.accounts.permissions import IsRegistrarOrAdmin
from apps.accounts.serializers import (
    AccountActivationConfirmSerializer,
    AccountActivationRequestSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)


class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsRegistrarOrAdmin]
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email", "university_id"]
    ordering_fields = ["created_at", "updated_at", "username"]

    def get_permissions(self):
        """
        Granular permission control:
        - ME: authenticated users can manage their own profile
        - PASSWORD_CHANGE: authenticated users can change their own password
        - DELETE: admin only
        - Other actions: registrar or admin
        """
        if self.action in ["me", "password_change"]:
            return [IsAuthenticated()]
        if self.action == "destroy":
            return [IsAdminUser()]
        return [IsRegistrarOrAdmin()]

    def me(self, request, *args, **kwargs):
        """Return or update the authenticated user's own profile."""
        if request.method == "GET":
            serializer = UserProfileSerializer(request.user)
            return Response(serializer.data, status=HTTP_200_OK)

        partial = request.method == "PATCH"
        serializer = UserProfileSerializer(
            instance=request.user,
            data=request.data,
            partial=partial,
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=HTTP_200_OK)

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated],
    )
    def password_change(self, request):
        """Change authenticated user's password."""
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"detail": "Password changed successfully."},
                status=HTTP_200_OK,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[],
    )
    def password_reset(self, request):
        """Request a password reset token (sent to email in production)."""
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            reset_data = serializer.save()
            user = reset_data["user"]
            token = reset_data["token"]
            
            # TODO: In production, send token via email
            # For development, return token in response
            return Response(
                {
                    "detail": "Password reset token generated.",
                    "uid": user.id,
                    "token": token,  # Remove in production (send via email instead)
                },
                status=HTTP_200_OK,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[],
    )
    def password_reset_confirm(self, request):
        """Confirm password reset with token and set new password."""
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"detail": "Password reset successfully."},
                status=HTTP_200_OK,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[],
    )
    def register(self, request):
        """Register a new user (student or lecturer only)."""
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(
                {
                    "detail": "User registered successfully.",
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                },
                status=HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[],
    )
    def activate_request(self, request):
        """Request account activation email (for inactive users)."""
        serializer = AccountActivationRequestSerializer(data=request.data)
        if serializer.is_valid():
            activation_data = serializer.save()
            user = activation_data["user"]
            token = activation_data["token"]

            # TODO: In production, send activation email
            # For development, return token and uid for manual testing
            return Response(
                {
                    "detail": "Activation link has been sent to your email.",
                    "uid": user.id,
                    "token": token,  # Remove in production (send via email instead)
                },
                status=HTTP_200_OK,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[],
    )
    def activate_confirm(self, request):
        """Confirm account activation with token."""
        serializer = AccountActivationConfirmSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"detail": "Account activated successfully. You can now log in."},
                status=HTTP_200_OK,
            )

        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

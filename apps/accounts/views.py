from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
import requests

from .models import User
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _tokens(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        email = d["email"].lower()
        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)

        university_id = d.get("university_id") or None
        if university_id and User.objects.filter(university_id=university_id).exists():
            return Response({"detail": "University ID already registered."}, status=400)

        parts = d["full_name"].split(" ", 1)
        user = User.objects.create_user(
            username=email,
            email=email,
            password=d["password"],
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else "",
            university_id=university_id,
            role=User.Role.STUDENT,
        )
        return Response(
            {"user": UserSerializer(user).data, **_tokens(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(
            username=s.validated_data["email"].lower(),
            password=s.validated_data["password"],
        )
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({"user": UserSerializer(user).data, **_tokens(user)})


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        user = request.user
        full_name = request.data.get("full_name")
        if full_name:
            parts = full_name.split(" ", 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
        if "phone_number" in request.data:
            user.phone_number = request.data["phone_number"]
        user.save()
        return Response(UserSerializer(user).data)


class GoogleAuthView(APIView):
    """
    POST /api/v1/auth/google/
    Body: { "id_token": "<Google ID token from Firebase>" }
    Returns: { "user": {...}, "access": "...", "refresh": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response({"detail": "id_token is required."}, status=400)

        # Verify token with Google
        try:
            resp = requests.get(
                GOOGLE_TOKEN_INFO_URL,
                params={"id_token": id_token},
                timeout=10,
            )
            if resp.status_code != 200:
                return Response(
                    {"detail": "Invalid Google token. Please try again."},
                    status=401,
                )
            google_data = resp.json()
        except requests.RequestException:
            return Response(
                {"detail": "Could not verify token with Google. Check your connection."},
                status=503,
            )

        # Extract user info from verified token
        email = google_data.get("email")
        email_verified = google_data.get("email_verified") is True  # Fixed boolean check
        full_name = google_data.get("name", "")

        if not email:
            return Response({"detail": "Google account has no email address."}, status=400)

        if not email_verified:
            return Response({"detail": "Google email is not verified."}, status=400)

        # Create or retrieve the user
        with transaction.atomic():
            user = User.objects.filter(email=email.lower()).first()

            if user:
                # Existing user — update name if they haven't set one yet
                if not user.first_name and full_name:
                    parts = full_name.split(" ", 1)
                    user.first_name = parts[0]
                    user.last_name = parts[1] if len(parts) > 1 else ""
                    user.save(update_fields=["first_name", "last_name"])
            else:
                # New user — create account from Google data
                parts = full_name.split(" ", 1) if full_name else ["", ""]
                user = User.objects.create_user(
                    username=email.lower(),
                    email=email.lower(),
                    password=None,  # No password — Google is the auth method
                    first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                    role=User.Role.STUDENT,
                )

        return Response({
            "user": UserSerializer(user).data,
            **_tokens(user),
        })

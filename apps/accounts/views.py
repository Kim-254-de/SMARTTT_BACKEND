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

# Firebase token verification — accepts Firebase ID tokens (what Flutter sends)
FIREBASE_VERIFY_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:lookup"
    "?key=AIzaSyAwYcCoaR0pRPli20r0LQIy3h-R1lHep1c"
)


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
    Body: { "id_token": "<Firebase ID token>" }
    Returns: { "user": {...}, "access": "...", "refresh": "..." }

    Flutter sends a Firebase ID token (not a raw Google OAuth token).
    We verify it via Firebase's accounts:lookup endpoint, which returns
    the user's profile from Firebase Auth.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response({"detail": "id_token is required."}, status=400)

        # Verify Firebase ID token
        try:
            resp = requests.post(
                FIREBASE_VERIFY_URL,
                json={"idToken": id_token},
                timeout=10,
            )
            if resp.status_code != 200:
                return Response(
                    {"detail": "Invalid Google token. Please try again."},
                    status=401,
                )
            firebase_data = resp.json()
        except requests.RequestException:
            return Response(
                {"detail": "Could not verify token with Google. Check your connection."},
                status=503,
            )

        # Firebase returns a users array
        users_list = firebase_data.get("users", [])
        if not users_list:
            return Response({"detail": "Token verification failed."}, status=401)

        user_info = users_list[0]

        # Extract user info — Firebase field names differ from Google's tokeninfo
        email = user_info.get("email")
        email_verified = user_info.get("emailVerified", False)
        full_name = user_info.get("displayName", "")

        if not email:
            return Response({"detail": "Google account has no email address."}, status=400)

        if not email_verified:
            return Response({"detail": "Google email is not verified."}, status=400)

        # Create or retrieve the user
        with transaction.atomic():
            user = User.objects.filter(email=email.lower()).first()

            if user:
                # Existing user — update name if not set
                if not user.first_name and full_name:
                    parts = full_name.split(" ", 1)
                    user.first_name = parts[0]
                    user.last_name = parts[1] if len(parts) > 1 else ""
                    user.save(update_fields=["first_name", "last_name"])
            else:
                # New user — create from Google data, no password needed
                parts = full_name.split(" ", 1) if full_name else ["", ""]
                user = User.objects.create_user(
                    username=email.lower(),
                    email=email.lower(),
                    password=None,
                    first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                    role=User.Role.STUDENT,
                )

        return Response({
            "user": UserSerializer(user).data,
            **_tokens(user),
        })

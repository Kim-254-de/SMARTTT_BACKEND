from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.serializers.auth_serializers import (
    LoginSerializer, RegisterSerializer, UserSerializer,
)
from apps.students.models import Student


def _tokens(user):
    r = RefreshToken.for_user(user)
    return {"access": str(r.access_token), "refresh": str(r)}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        ser = RegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        email = d["email"]
        admission = d.get("admission_number") or None

        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)
        if admission and User.objects.filter(university_id=admission).exists():
            return Response({"detail": "Admission number already registered."}, status=400)

        parts = d["full_name"].split(" ", 1)
        user = User.objects.create_user(
            username=email, email=email, password=d["password"],
            first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
            university_id=admission, role=User.Role.STUDENT,
        )

        # Create a minimal Student profile so personalization works immediately
        Student.objects.create(
            user=user,
            full_name=d["full_name"],
            admission_number=admission or f"STU-{user.id}",
            program_name=d.get("course",""),
            year_of_study=d.get("year_of_study",1),
        )

        return Response({"tokens": _tokens(user), "user": UserSerializer(user).data}, status=201)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = authenticate(username=ser.validated_data["email"], password=ser.validated_data["password"])
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=401)
        return Response({"tokens": _tokens(user), "user": UserSerializer(user).data})


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

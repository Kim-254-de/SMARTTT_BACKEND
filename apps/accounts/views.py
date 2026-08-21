from django.contrib.auth import authenticate
from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser
from django.utils import timezone
from datetime import timedelta
import os
import secrets
import requests
import resend

from .models import PasswordResetToken, User
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

resend.api_key = settings.RESEND_API_KEY

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


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if user is None:
            return Response({"detail": "If that email exists, a reset link has been sent."})

        token = secrets.token_urlsafe(32)
        while PasswordResetToken.objects.filter(token=token).exists():
            token = secrets.token_urlsafe(32)

        expires_at = timezone.now() + timedelta(minutes=15)
        PasswordResetToken.objects.create(user=user, token=token, expires_at=expires_at)

        reset_url = f"https://nextup.co.ke/reset-password.html?token={token}"

        try:
            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [user.email],
                "subject": "Reset your NextUp password",
                "html": f"""
                    <div style="margin:0;background:#f5f7fb;padding:40px 16px;font-family:Arial,sans-serif;color:#172033;">
                      <div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e5e9f2;border-radius:16px;padding:40px;">
                        <h1 style="margin:0 0 20px;font-size:26px;color:#172033;">Reset your password</h1>
                        <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">Hello {user.get_full_name() or user.email},</p>
                        <p style="margin:0 0 28px;font-size:16px;line-height:1.6;">We received a request to set a new password for your NextUp account.</p>
                        <p style="margin:0 0 28px;"><a href="{reset_url}" style="display:inline-block;background:#2563eb;color:#ffffff;padding:14px 24px;border-radius:8px;text-decoration:none;font-weight:700;">Set New Password</a></p>
                        <p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#526078;">This link expires strictly in 15 minutes.</p>
                        <p style="margin:0;font-size:14px;line-height:1.6;color:#526078;">If you did not request this reset, you can safely ignore this email.</p>
                      </div>
                    </div>
                """,
            })
        except Exception:
            return Response(
                {"detail": "Unable to send password reset email."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"detail": "If that email exists, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = str(request.data.get("token", "")).strip()
        new_password = str(request.data.get("new_password", ""))
        confirm_password = str(request.data.get("confirm_password", ""))

        if not token:
            return Response({"detail": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password:
            return Response({"detail": "New password is required."}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({"detail": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 6:
            return Response({"detail": "Password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)

        reset_token = PasswordResetToken.objects.select_related("user").filter(
            token=token,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).first()

        if reset_token is None:
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)

        user = reset_token.user
        user.set_password(new_password)
        user.save(update_fields=["password"])

        reset_token.is_used = True
        reset_token.save(update_fields=["is_used"])

        return Response({"detail": "Password updated successfully."})


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
        
        
class LecturerRegisterView(APIView):
    """
    POST /api/v1/auth/lecturer/register/
    Lecturer self-registration — validates staff ID against pre-loaded list.
    Body: {
        "staff_id": "TUN/ST/001",
        "email": "lecturer@tharaka.ac.ke",
        "full_name": "Dr. Jane Doe",
        "password": "...",
        "department": "<department_uuid>"  // optional
    }
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        staff_id = request.data.get("staff_id", "").strip()
        email = request.data.get("email", "").strip().lower()
        full_name = request.data.get("full_name", "").strip()
        password = request.data.get("password", "")
        department_id = request.data.get("department")

        if not all([staff_id, email, full_name, password]):
            return Response(
                {"detail": "staff_id, email, full_name, and password are required."},
                status=400,
            )

        if len(password) < 6:
            return Response({"detail": "Password must be at least 6 characters."}, status=400)

        # Validate staff ID
        from apps.core.models import ValidStaffID, Department, Lecturer
        try:
            valid_staff = ValidStaffID.objects.get(staff_id__iexact=staff_id)
        except ValidStaffID.DoesNotExist:
            return Response(
                {"detail": "Staff ID not found. Please contact the university ICT department."},
                status=400,
            )

        if valid_staff.is_claimed:
            return Response(
                {"detail": "This staff ID has already been registered. Contact ICT if this is an error."},
                status=400,
            )

        # Check email not already used
        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)

        # Resolve department
        department = None
        if department_id:
            try:
                department = Department.objects.get(pk=department_id)
            except Department.DoesNotExist:
                pass

        # Create User
        parts = full_name.split(" ", 1)
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=parts[0],
            last_name=parts[1] if len(parts) > 1 else "",
            university_id=staff_id,
            role=User.Role.LECTURER,
        )

        # Create Lecturer profile
        if department:
            Lecturer.objects.create(user=user, department=department, title="")

        # Mark staff ID as claimed
        valid_staff.is_claimed = True
        valid_staff.save(update_fields=["is_claimed"])

        return Response(
            {"user": UserSerializer(user).data, **_tokens(user)},
            status=status.HTTP_201_CREATED,
        )


class StaffIDUploadView(APIView):
    """
    POST /api/v1/auth/staff-ids/upload/
    Admin uploads a CSV of valid staff IDs.
    CSV format: staff_id,name (header row optional)
    """
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        import csv, io
        from apps.core.models import ValidStaffID

        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=400)

        try:
            content = file.read().decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            created = 0
            skipped = 0
            for row in reader:
                if not row:
                    continue
                staff_id = row[0].strip()
                if not staff_id or staff_id.lower() == "staff_id":
                    continue  # skip header or empty
                name_hint = row[1].strip() if len(row) > 1 else ""
                _, was_created = ValidStaffID.objects.get_or_create(
                    staff_id=staff_id,
                    defaults={"name_hint": name_hint},
                )
                if was_created:
                    created += 1
                else:
                    skipped += 1
        except Exception as exc:
            return Response({"detail": f"Could not parse CSV: {exc}"}, status=400)

        return Response({
            "detail": f"Uploaded {created} new staff ID(s). {skipped} already existed."
        })


class StaffIDListView(APIView):
    """
    GET /api/v1/auth/staff-ids/
    Admin views all staff IDs and their claim status.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.core.models import ValidStaffID
        ids = ValidStaffID.objects.all().values("staff_id", "name_hint", "is_claimed", "uploaded_at")
        return Response(list(ids))


class LecturerProfileView(APIView):
    """
    GET /api/v1/auth/lecturer/profile/
    
    Returns the lecturer's assigned slots for the current term.
    
    Matching priority:
      1. Slots where lecturer FK = this lecturer's profile (ideal — requires
         lecturers to be linked during timetable upload)
      2. Fallback: ALL units for the current term — lecturer self-selects
         which units they teach. This handles the common case where the
         Excel timetable has no lecturer assignments filled in.
    
    The response includes a "slot_source" field:
      "assigned"  — slots matched to this lecturer directly
      "all_units" — fallback, lecturer must self-identify their units
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.timetable.models import AcademicTerm, TimetableSlot
        from apps.timetable.serializers import TimetableSlotSerializer
        from apps.core.models import Lecturer

        user = request.user
        if user.role not in ["lecturer"]:
            return Response({"detail": "Not a lecturer account."}, status=403)

        term = AcademicTerm.objects.filter(is_current=True).first()
        slots = []
        slot_source = "none"

        if term:
            # ── Priority 1: slots directly assigned to this lecturer ──────────
            try:
                lecturer_profile = Lecturer.objects.get(user=user)
                assigned_slots = TimetableSlot.objects.select_related(
                    "unit", "program", "room", "term"
                ).filter(term=term, lecturer=lecturer_profile)

                if assigned_slots.exists():
                    slots = TimetableSlotSerializer(assigned_slots, many=True).data
                    slot_source = "assigned"
            except Lecturer.DoesNotExist:
                pass

            # ── Priority 2: fallback — return all units this term ─────────────
            if not slots:
                all_slots = TimetableSlot.objects.select_related(
                    "unit", "program", "room", "term"
                ).filter(term=term).order_by("day", "start_time")
                slots = TimetableSlotSerializer(all_slots, many=True).data
                slot_source = "all_units"

        return Response({
            "user": UserSerializer(user).data,
            "current_term": str(term) if term else None,
            "slots": slots,
            "slot_source": slot_source,
        })
class LecturerStudentsView(APIView):
    """
    GET /api/v1/auth/lecturer/students/?unit=<unit_id>
    Returns students enrolled in a specific unit this term.
    
    In fallback mode (no lecturer assignments in timetable),
    any verified lecturer can query any unit.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.timetable.models import AcademicTerm
        from apps.courses.models import StudentUnit
        from apps.core.models import Lecturer

        user = request.user
        if user.role not in ["lecturer"]:
            return Response({"detail": "Not a lecturer account."}, status=403)

        unit_id = request.query_params.get("unit")
        if not unit_id:
            return Response({"detail": "unit query param is required."}, status=400)

        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            return Response({"detail": "No current term."}, status=400)

        # Check if lecturer is assigned to this unit (strict mode)
        # If not assigned, still allow access (fallback mode)
        try:
            lecturer_profile = Lecturer.objects.get(user=user)
            is_assigned = TimetableSlot.objects.filter(
                term=term, unit_id=unit_id, lecturer=lecturer_profile
            ).exists()
        except Lecturer.DoesNotExist:
            is_assigned = False
        # In fallback mode we allow all verified lecturers to view any unit's students

        students = StudentUnit.objects.select_related(
            "user", "unit"
        ).filter(unit_id=unit_id, term=term)

        return Response([
            {
                "id": str(su.user.id),
                "name": su.user.get_full_name(),
                "email": su.user.email,
                "university_id": su.user.university_id,
            }
            for su in students
        ])

from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser
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

        university_id = d.get("admission_number") or d.get("university_id") or None
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
        if "admission_number" in request.data or "university_id" in request.data:
            admission_number = request.data.get("admission_number")
            if admission_number is None:
                admission_number = request.data.get("university_id")
            admission_number = admission_number or None
            if (
                admission_number
                and User.objects.filter(university_id=admission_number)
                .exclude(pk=user.pk)
                .exists()
            ):
                return Response(
                    {"detail": "This admission number is already in use."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user.university_id = admission_number
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
            # ── Priority 1: slots directly assigned via lecturer FK ───────────
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

            # ── Priority 2: match by lecturer_name_text from allocation sheet ─
            if not slots:
                full_name = user.get_full_name().strip()
                first_name = user.first_name.strip()
                last_name = user.last_name.strip()

                from django.db.models import Q
                name_matched_slots = TimetableSlot.objects.select_related(
                    "unit", "program", "room", "term"
                ).filter(
                    term=term,
                    lecturer_name_text__isnull=False,
                ).filter(
                    Q(lecturer_name_text__icontains=full_name) |
                    Q(lecturer_name_text__icontains=last_name) |
                    Q(lecturer_name_text__icontains=first_name)
                ).exclude(lecturer_name_text='')

                if name_matched_slots.exists():
                    slots = TimetableSlotSerializer(name_matched_slots, many=True).data
                    slot_source = "name_matched"

                    # Auto-link the lecturer FK now that we found a match
                    try:
                        lecturer_profile = Lecturer.objects.get(user=user)
                    except Lecturer.DoesNotExist:
                        dept = name_matched_slots.first().unit.department
                        lecturer_profile = Lecturer.objects.create(
                            user=user, department=dept, title=""
                        )
                    name_matched_slots.update(lecturer=lecturer_profile)

            # ── Priority 3: no match found ─────────────────────────────────────
            if not slots:
                slot_source = "no_match"

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

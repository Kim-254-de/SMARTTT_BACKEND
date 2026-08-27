from datetime import timedelta
import re
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
import requests
import resend

from apps.accounts.models import PasswordResetToken, User
from apps.departments.models import Department, Faculty
from apps.programs.models.program import Program
from apps.students.models.student import Student
from apps.timetable.models import AcademicTerm

resend.api_key = settings.RESEND_API_KEY

# Using Django sessions instead of issuing JWTs; login the user to create a session

def serialize_user(user):
    student = getattr(user, 'student_profile', None)
    program = getattr(student, 'program', None)
    department = getattr(program, 'department', None) if program else None
    
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.get_full_name(),
        "admission_number": user.university_id,
        "course": getattr(program, 'name', None),
        "department": getattr(department, 'name', None),
        "year_of_study": getattr(student, 'current_study_year', None),
    }

class RegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        data = request.data
        email = data.get('email')
        password = data.get('password')
        full_name = data.get('full_name', '')
        admission_number = data.get('admission_number')
        course_name = data.get('course')
        department_name = data.get('department')
        try:
            year_of_study = int(data.get('year_of_study', 1))
        except (ValueError, TypeError):
            year_of_study = 1

        if User.objects.filter(email=email).exists() or User.objects.filter(username=email).exists():
            return Response({"detail": "User with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)
        if admission_number and User.objects.filter(university_id=admission_number).exists():
            return Response({"detail": "User with this admission number already exists."}, status=status.HTTP_400_BAD_REQUEST)

        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            university_id=admission_number if admission_number else None,
            role=User.Role.STUDENT
        )

        if department_name and course_name:
            dept_code = re.sub(r'[^A-Z]', '', department_name.upper())[:20]
            if not dept_code: dept_code = department_name.upper()[:20]

            # Use a generic faculty instead of naming it after the department
            faculty, _ = Faculty.objects.get_or_create(
                code="GEN",
                defaults={'name': 'General Faculty'}
            )
            
            department, _ = Department.objects.get_or_create(
                faculty=faculty,
                name=department_name,
                defaults={'code': dept_code, 'faculty': faculty}
            )
            
            prog_code = re.sub(r'[^A-Z]', '', course_name.upper())[:30]
            if not prog_code: prog_code = course_name.upper()[:30]

            program, _ = Program.objects.get_or_create(
                department=department,
                name=course_name,
                defaults={
                    'code': prog_code,
                    'department': department,
                    'duration_years': max(4, year_of_study)
                }
            )
            if program.duration_years < year_of_study:
                program.duration_years = year_of_study
                program.save(update_fields=['duration_years'])

            reg_num = re.sub(r'[^A-Z0-9\-]', '', admission_number.upper()) if admission_number else f"STU-{user.id}"
            if not reg_num:
                reg_num = f"STU-{user.id}"

            admission_yr = timezone.now().year
            if reg_num:
                match = re.search(r'[/\-](\d{2,4})$', reg_num.strip())
                if match:
                    yr_str = match.group(1)
                    if len(yr_str) == 2:
                        admission_yr = 2000 + int(yr_str)
                    elif len(yr_str) == 4:
                        admission_yr = int(yr_str)
                else:
                    match = re.search(r'^(\d{2})[/\-]', reg_num.strip())
                    if match:
                        admission_yr = 2000 + int(match.group(1))

            current_term = AcademicTerm.objects.filter(is_current=True).first()
            current_sem = current_term.semester if current_term else 1

            Student.objects.create(
                user=user,
                registration_number=reg_num,
                first_name=first_name or "First",
                last_name=last_name or "Last",
                email=email,
                department=department,
                program=program,
                admission_year=admission_yr,
                current_study_year=year_of_study,
                current_semester=current_sem
            )

        # Log the user in to create a session cookie
        login(request, user)
        return Response({"user": serialize_user(user)}, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        user = authenticate(username=email, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, user)
        return Response({"user": serialize_user(user)})

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serialize_user(request.user))

    @transaction.atomic
    def patch(self, request):
        user = request.user
        data = request.data
        
        full_name = data.get('full_name')
        if full_name:
            name_parts = full_name.split(' ', 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            
        if 'admission_number' in data:
            user.university_id = data['admission_number']
            
        user.save()

        student = getattr(user, 'student_profile', None)
        if student:
            if 'year_of_study' in data:
                try:
                    student.current_study_year = int(data['year_of_study'])
                except (ValueError, TypeError):
                    pass
            if 'course' in data and 'department' in data:
                dept_code = re.sub(r'[^A-Z]', '', data['department'].upper())[:20]
                if not dept_code: dept_code = data['department'].upper()[:20]

                faculty, _ = Faculty.objects.get_or_create(
                    code="GEN",
                    defaults={"name": "General", "description": "Default faculty"},
                )

                dept, _ = Department.objects.get_or_create(
                    faculty=faculty,
                    name=data['department'],
                    defaults={'code': dept_code},
                )
                
                prog_code = re.sub(r'[^A-Z]', '', data['course'].upper())[:30]
                if not prog_code: prog_code = data['course'].upper()[:30]
                
                study_year = student.current_study_year
                prog, _ = Program.objects.get_or_create(
                    department=dept,
                    name=data['course'],
                    defaults={
                        'code': prog_code,
                        'department': dept,
                        'duration_years': max(4, study_year)
                    }
                )
                if prog.duration_years < study_year:
                    prog.duration_years = study_year
                    prog.save(update_fields=['duration_years'])
                student.program = prog
                student.department = dept
            student.save()

        return Response(serialize_user(user))


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        if not email:
            return Response({'detail': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if user is None:
            return Response({'detail': 'If that email exists, a reset link has been sent.'})

        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)

        token = secrets.token_urlsafe(32)
        while PasswordResetToken.objects.filter(token=token).exists():
            token = secrets.token_urlsafe(32)

        expires_at = timezone.now() + timedelta(minutes=15)
        PasswordResetToken.objects.create(user=user, token=token, expires_at=expires_at)

        reset_url = f'https://nextup.co.ke/reset-password.html?token={token}'

        try:
            resend.Emails.send({
                'from': settings.DEFAULT_FROM_EMAIL,
                'to': [user.email],
                'subject': 'Reset your NextUp password',
                'html': f'''
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
                ''',
            })
        except Exception:
            return Response(
                {'detail': 'Unable to send password reset email.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({'detail': 'If that email exists, a reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = str(request.data.get('token', '')).strip()
        new_password = str(request.data.get('new_password', ''))
        confirm_password = str(request.data.get('confirm_password', ''))

        if not token:
            return Response({'detail': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password:
            return Response({'detail': 'New password is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != confirm_password:
            return Response({'detail': 'Passwords do not match.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 6:
            return Response({'detail': 'Password must be at least 6 characters.'}, status=status.HTTP_400_BAD_REQUEST)

        reset_token = PasswordResetToken.objects.select_related('user').filter(
            token=token,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).first()

        if reset_token is None:
            return Response({'detail': 'Invalid or expired link.'}, status=status.HTTP_400_BAD_REQUEST)

        user = reset_token.user
        user.set_password(new_password)
        user.save(update_fields=['password'])

        reset_token.is_used = True
        reset_token.save(update_fields=['is_used'])

        return Response({'detail': 'Password updated successfully.'})


FIREBASE_VERIFY_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:lookup"
    "?key=AIzaSyAwYcCoaR0pRPli20r0LQIy3h-R1lHep1c"
)


class GoogleAuthView(APIView):
    """
    POST /api/v1/auth/google/
    Body: { "id_token": "<Firebase ID token>" }
    Returns: { "user": {...}, "access": "...", "refresh": "..." }
    """

    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response({"detail": "id_token is required."}, status=400)

        try:
            resp = requests.post(
                FIREBASE_VERIFY_URL,
                json={"idToken": id_token},
                timeout=10,
            )
            if resp.status_code != 200:
                return Response({"detail": "Invalid Google token. Please try again."}, status=401)
            firebase_data = resp.json()
        except requests.RequestException:
            return Response({"detail": "Could not verify token with Google. Check your connection."}, status=503)

        users_list = firebase_data.get("users", [])
        if not users_list:
            return Response({"detail": "Token verification failed."}, status=401)

        user_info = users_list[0]
        email = user_info.get("email")
        email_verified = user_info.get("emailVerified", False)
        full_name = user_info.get("displayName", "")

        if not email:
            return Response({"detail": "Google account has no email address."}, status=400)
        if not email_verified:
            return Response({"detail": "Google email is not verified."}, status=400)

        with transaction.atomic():
            user = User.objects.filter(email=email.lower()).first()
            if user:
                if not user.first_name and full_name:
                    parts = full_name.split(" ", 1)
                    user.first_name = parts[0]
                    user.last_name = parts[1] if len(parts) > 1 else ""
                    user.save(update_fields=["first_name", "last_name"])
            else:
                parts = full_name.split(" ", 1) if full_name else ["", ""]
                user = User.objects.create_user(
                    username=email.lower(),
                    email=email.lower(),
                    password=None,
                    first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                    role=User.Role.STUDENT,
                )

        return Response({"user": UserSerializer(user).data, **get_tokens_for_user(user)})


class LecturerRegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        staff_id = request.data.get("staff_id", "").strip()
        email = request.data.get("email", "").strip().lower()
        full_name = request.data.get("full_name", "").strip()
        password = request.data.get("password", "")
        department_id = request.data.get("department")

        if not all([staff_id, email, full_name, password]):
            return Response({"detail": "staff_id, email, full_name, and password are required."}, status=400)
        if len(password) < 6:
            return Response({"detail": "Password must be at least 6 characters."}, status=400)

        from apps.core.models import ValidStaffID, Department, Lecturer

        try:
            valid_staff = ValidStaffID.objects.get(staff_id__iexact=staff_id)
        except ValidStaffID.DoesNotExist:
            return Response({"detail": "Staff ID not found. Please contact the university ICT department."}, status=400)

        if valid_staff.is_claimed:
            return Response({"detail": "This staff ID has already been registered. Contact ICT if this is an error."}, status=400)

        if User.objects.filter(email=email).exists():
            return Response({"detail": "Email already registered."}, status=400)

        department = None
        if department_id:
            try:
                department = Department.objects.get(pk=department_id)
            except Department.DoesNotExist:
                pass

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

        if department:
            Lecturer.objects.create(user=user, department=department, title="")

        valid_staff.is_claimed = True
        valid_staff.save(update_fields=["is_claimed"])

        return Response({"user": UserSerializer(user).data, **get_tokens_for_user(user)}, status=status.HTTP_201_CREATED)


class StaffIDUploadView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        import csv
        import io

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
                    continue
                name_hint = row[1].strip() if len(row) > 1 else ""
                _, was_created = ValidStaffID.objects.get_or_create(staff_id=staff_id, defaults={"name_hint": name_hint})
                if was_created:
                    created += 1
                else:
                    skipped += 1
        except Exception as exc:
            return Response({"detail": f"Could not parse CSV: {exc}"}, status=400)

        return Response({"detail": f"Uploaded {created} new staff ID(s). {skipped} already existed."})


class StaffIDListView(APIView):
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
            try:
                lecturer_profile = Lecturer.objects.get(user=user)
                assigned_slots = TimetableSlot.objects.select_related("unit", "program", "room", "term").filter(term=term, lecturer=lecturer_profile)
                if assigned_slots.exists():
                    slots = TimetableSlotSerializer(assigned_slots, many=True).data
                    slot_source = "assigned"
            except Lecturer.DoesNotExist:
                pass

            if not slots:
                all_slots = TimetableSlot.objects.select_related("unit", "program", "room", "term").filter(term=term).order_by("day", "start_time")
                slots = TimetableSlotSerializer(all_slots, many=True).data
                slot_source = "all_units"

        return Response({"user": UserSerializer(user).data, "current_term": str(term) if term else None, "slots": slots, "slot_source": slot_source})


class LecturerStudentsView(APIView):
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

        try:
            lecturer_profile = Lecturer.objects.get(user=user)
            is_assigned = TimetableSlot.objects.filter(term=term, unit_id=unit_id, lecturer=lecturer_profile).exists()
        except Lecturer.DoesNotExist:
            is_assigned = False

        students = StudentUnit.objects.select_related("user", "unit").filter(unit_id=unit_id, term=term)
        return Response({"detail": "ok", "is_assigned": is_assigned, "students": []})

class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        return Response({"detail": "Password reset email sent."})

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)

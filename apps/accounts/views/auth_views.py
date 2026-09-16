from datetime import timedelta
import re
import secrets

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Q
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
from apps.accounts.serializers.user_serializer import UserSerializer
from apps.departments.models import Department, Faculty
from apps.programs.models.program import Program
from apps.students.models.student import Student
from apps.timetable.models import AcademicTerm

resend.api_key = settings.RESEND_API_KEY


def get_tokens_for_user(user):
    """Issue a fresh JWT access/refresh pair for a user."""
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


def serialize_user(user):
    student = getattr(user, 'student_profile', None)
    program = getattr(student, 'program', None)
    department = getattr(program, 'department', None) if program else None
    
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.get_full_name(),
        "role": user.role,
        "university_id": user.university_id,
        "phone_number": user.phone_number,
        "course": getattr(program, 'name', None),
        "department": getattr(department, 'name', None),
        "year_of_study": getattr(student, 'current_study_year', None),
        "combination": getattr(student, 'combination', None),
        "timetable_group": getattr(student, 'timetable_group', None),
    }


def _derive_registration_number(user) -> str:
    reg_num = re.sub(r'[^A-Z0-9\-]', '', (user.university_id or '').upper())
    return reg_num or f"STU-{user.id}"


def _derive_admission_year(admission_number: str | None) -> int:
    """Best-effort admission year from an admission number like 'ABT5/10954/24'."""
    admission_yr = timezone.now().year
    reg_num = re.sub(r'[^A-Z0-9\-/]', '', (admission_number or '').upper()).strip()
    if not reg_num:
        return admission_yr

    match = re.search(r'[/\-](\d{2,4})$', reg_num)
    if match:
        yr_str = match.group(1)
        if len(yr_str) == 2:
            admission_yr = 2000 + int(yr_str)
        elif len(yr_str) == 4:
            admission_yr = int(yr_str)
    else:
        match = re.search(r'^(\d{2})[/\-]', reg_num)
        if match:
            admission_yr = 2000 + int(match.group(1))
    return admission_yr


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
        combination = data.get('combination', '').strip()
        timetable_group = data.get('timetable_group', '').strip()
        
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

            reg_num = _derive_registration_number(user)
            admission_yr = _derive_admission_year(admission_number)

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
                current_semester=current_sem,
                combination=combination,
                timetable_group=timetable_group,
            )

        tokens = get_tokens_for_user(user)
        return Response({
            "access": tokens['access'],
            "refresh": tokens['refresh'],
            "user": serialize_user(user)
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        login_id = str(request.data.get('email') or request.data.get('username') or request.data.get('staff_id') or '').strip()
        password = request.data.get('password')

        if not login_id or not password:
            return Response({"detail": "Username/email/staff ID and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        user_obj = User.objects.filter(
            Q(email__iexact=login_id) | 
            Q(username__iexact=login_id) | 
            Q(university_id__iexact=login_id)
        ).first()

        user = None
        if user_obj:
            user = authenticate(username=user_obj.username, password=password)
        else:
            user = authenticate(username=login_id, password=password)

        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        tokens = get_tokens_for_user(user)
        return Response({
            "access": tokens['access'],
            "refresh": tokens['refresh'],
            "user": serialize_user(user)
        })


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

        if 'phone_number' in data:
            user.phone_number = data['phone_number']

        user.save()

        student = getattr(user, 'student_profile', None)

        year_of_study = None
        if 'year_of_study' in data:
            try:
                year_of_study = int(data['year_of_study'])
            except (ValueError, TypeError):
                year_of_study = None

        resolved_program = None
        if data.get('program_id'):
            # Preferred path: the student picked their course from
            # timetable/metadata/, which only lists Program rows the
            # master timetable upload actually created — linking to
            # this exact row (rather than get_or_create-ing a new one
            # by name below) is what lets schedule generation match
            # TimetableSlot.program correctly.
            try:
                resolved_program = Program.objects.select_related('department').get(
                    pk=data['program_id']
                )
            except (Program.DoesNotExist, ValueError, TypeError):
                resolved_program = None

        if not resolved_program and 'course' in data and 'department' in data:
            # Fallback only: used when resolution above failed/wasn't
            # provided (e.g. a term with no timetable slots yet). This
            # get_or_create-by-name path creates its own Program/Department
            # rows and will NOT generally match the ones the master
            # timetable upload created, so it should not be relied on
            # once slots exist.
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

            study_year = year_of_study or (student.current_study_year if student else 1)
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
            resolved_program = prog

        if student is None:
            # A student who registered without picking a course yet (the
            # normal signup flow - see RegisterView, which only creates a
            # Student row when department+course are given upfront) has no
            # profile to update here. Without this, every field below was
            # silently discarded: the stream-setup screen showed "saved"
            # but nothing was ever persisted, and personalised-schedule
            # generation and /timetable/metadata/ never respected the
            # student's actual program/year/stream.
            if resolved_program:
                current_term = AcademicTerm.objects.filter(is_current=True).first()
                student = Student.objects.create(
                    user=user,
                    registration_number=_derive_registration_number(user),
                    first_name=user.first_name or "First",
                    last_name=user.last_name or "Last",
                    email=user.email,
                    department=resolved_program.department,
                    program=resolved_program,
                    admission_year=_derive_admission_year(user.university_id),
                    current_study_year=year_of_study or 1,
                    current_semester=current_term.semester if current_term else 1,
                    combination=str(data.get('combination', '')).strip(),
                    timetable_group=str(data.get('timetable_group', '')).strip(),
                )
        else:
            if year_of_study is not None:
                student.current_study_year = year_of_study
            if 'combination' in data:
                student.combination = str(data['combination']).strip()
            if 'timetable_group' in data:
                student.timetable_group = str(data['timetable_group']).strip()
            if resolved_program:
                student.program = resolved_program
                student.department = resolved_program.department
            student.save()

        return Response(serialize_user(user))


class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = request.user
        password = request.data.get('password')

        if not password:
            return Response(
                {"detail": "Current password is required to delete your account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.check_password(password):
            return Response(
                {"detail": "Incorrect password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots_unassigned = 0
        lecturer = getattr(user, 'lecturer_profile', None)
        if lecturer:
            from apps.timetable.models import TimetableSlot
            slots_unassigned = TimetableSlot.objects.filter(lecturer=lecturer).update(lecturer=None)

        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)

        user.is_active = False
        user.save(update_fields=['is_active'])

        return Response({
            "detail": "Account deleted. You have been logged out of all devices.",
            "slots_unassigned": slots_unassigned,
        })


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

        from apps.accounts.models import ValidStaffID
        from apps.departments.models import Department
        from apps.lecturers.models import Lecturer

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
            Lecturer.objects.create(user=user, department=department, rank="")

        valid_staff.is_claimed = True
        valid_staff.save(update_fields=["is_claimed"])

        return Response({"user": UserSerializer(user).data, **get_tokens_for_user(user)}, status=status.HTTP_201_CREATED)


class StaffIDUploadView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        import csv
        import io

        from apps.accounts.models import ValidStaffID

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
        from apps.accounts.models import ValidStaffID

        ids = ValidStaffID.objects.all().values("staff_id", "name_hint", "is_claimed", "uploaded_at")
        return Response(list(ids))


class LecturerProfileView(APIView):
    permission_classes = [IsAuthenticated]

    DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

    def get(self, request):
        from django.db.models import Q
        from django.utils import timezone

        from apps.courses.models import StudentUnit
        from apps.departments.models import Department
        from apps.lecturers.models import Lecturer
        from apps.timetable.models import AcademicTerm, TimetableSlot

        user = request.user
        if user.role not in ["lecturer"]:
            return Response({"detail": "Not a lecturer account."}, status=403)

        term = AcademicTerm.objects.filter(is_current=True).first()
        slots_data = []
        slot_source = "none"

        now = timezone.localtime()
        # Sunday (weekday() == 6) has no teaching day in DAY_ORDER — fall back
        # to Monday for display; today_sessions will simply be empty.
        today_code = self.DAY_ORDER[now.weekday()] if now.weekday() < 6 else "MON"

        lecturer_profile = None
        units_by_id: dict[str, dict] = {}
        timetable: dict[str, list] = {day: [] for day in self.DAY_ORDER}
        today_sessions = []
        weekly_sessions = 0
        unit_ids_taught: set = set()

        if term:
            lecturer_profile, _ = Lecturer.objects.get_or_create(
                user=user,
                defaults={"department": Department.objects.first(), "rank": ""}
            )

            first_name = user.first_name.strip()
            last_name = user.last_name.strip()

            name_query = Q()
            if first_name and last_name:
                name_query |= (Q(lecturer_name_text__icontains=first_name) & Q(lecturer_name_text__icontains=last_name))
            elif last_name:
                name_query |= Q(lecturer_name_text__icontains=last_name)
            elif first_name:
                name_query |= Q(lecturer_name_text__icontains=first_name)

            assigned_slots = TimetableSlot.objects.select_related(
                "unit", "program", "room", "term"
            ).filter(
                Q(term=term) & (Q(lecturer=lecturer_profile) | name_query)
            ).order_by("day_of_week", "start_time")

            if assigned_slots.exists():
                slot_source = "assigned"
                seen_signatures = set()
                # unit_id -> distinct StudentUnit count this term, computed once per unit
                student_count_by_unit: dict = {}

                for slot in assigned_slots:
                    if slot.lecturer_id != lecturer_profile.id:
                        slot.lecturer = lecturer_profile
                        slot.save(update_fields=["lecturer"])

                    sig = (slot.unit_id, slot.day_of_week, slot.start_time, slot.end_time, slot.room_id)
                    if sig in seen_signatures:
                        continue
                    seen_signatures.add(sig)

                    unit_id = str(slot.unit_id) if slot.unit_id else ""
                    unit_code = slot.unit.code if slot.unit else ""
                    unit_name = slot.unit.name if slot.unit else ""
                    day_key = (slot.day_of_week or "MON").upper()
                    start_str = slot.start_time.strftime("%H:%M") if slot.start_time else ""
                    end_str = slot.end_time.strftime("%H:%M") if slot.end_time else ""

                    # Legacy shape — still consumed by web/lecturer.html
                    slots_data.append({
                        "id": str(slot.id),
                        "unit": unit_id,
                        "unit_code": unit_code,
                        "unit_name": unit_name,
                        "day": day_key,
                        "start_time": slot.start_time.strftime("%H:%M:%S") if slot.start_time else "08:00:00",
                        "end_time": slot.end_time.strftime("%H:%M:%S") if slot.end_time else "10:00:00",
                        "room_code": slot.room.code if slot.room else "TBA",
                        "program_name": slot.program.name if slot.program else "",
                    })

                    if unit_id:
                        unit_ids_taught.add(slot.unit_id)
                        units_by_id.setdefault(unit_id, {"id": unit_id, "code": unit_code, "name": unit_name})

                        if slot.unit_id not in student_count_by_unit:
                            student_count_by_unit[slot.unit_id] = StudentUnit.objects.filter(
                                unit_id=slot.unit_id, term=term
                            ).count()
                    student_count = student_count_by_unit.get(slot.unit_id, 0)

                    session = {
                        "id": str(slot.id),
                        "unit_id": unit_id,
                        "unit_code": unit_code,
                        "unit_name": unit_name,
                        "day": day_key,
                        "start_time": start_str,
                        "end_time": end_str,
                        "room": slot.room.code if slot.room else "TBA",
                        "program": slot.program.name if slot.program else "",
                        "student_count": student_count,
                    }

                    weekly_sessions += 1
                    if day_key in timetable:
                        timetable[day_key].append(session)

                    if day_key == today_code and slot.start_time and slot.end_time:
                        current_time = now.time()
                        if current_time > slot.end_time:
                            status = "completed"
                        elif slot.start_time <= current_time <= slot.end_time:
                            status = "now"
                        else:
                            status = "upcoming"
                        today_sessions.append({**session, "status": status})

        for day in timetable:
            timetable[day].sort(key=lambda s: s["start_time"])
        today_sessions.sort(key=lambda s: s["start_time"])

        total_students = (
            StudentUnit.objects.filter(unit_id__in=unit_ids_taught, term=term)
            .values("user_id").distinct().count()
            if unit_ids_taught and term else 0
        )
        completed_today = sum(1 for s in today_sessions if s["status"] == "completed")
        remaining_today = len(today_sessions) - completed_today

        return Response({
            "user": UserSerializer(user).data,
            "lecturer": {
                "staff_id": user.university_id or "",
                "department": lecturer_profile.department.name if lecturer_profile and lecturer_profile.department else "",
                "rank": lecturer_profile.rank if lecturer_profile else "",
            },
            "current_term": str(term) if term else None,
            "today": today_code,
            "allocated_units": sorted({u["code"] for u in units_by_id.values() if u["code"]}),
            "units": list(units_by_id.values()),
            "summary": {
                "units_count": len(units_by_id),
                "weekly_sessions": weekly_sessions,
                "total_students": total_students,
                "completed_today": completed_today,
                "remaining_today": remaining_today,
            },
            "timetable": timetable,
            "today_sessions": today_sessions,
            # Legacy fields — kept so web/lecturer.html keeps working unchanged.
            "slots": slots_data,
            "slot_source": slot_source,
        })


class LecturerStudentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.timetable.models import AcademicTerm
        from apps.courses.models import StudentUnit

        user = request.user
        if user.role not in ["lecturer"]:
            return Response({"detail": "Not a lecturer account."}, status=403)

        unit_id = request.query_params.get("unit")
        if not unit_id:
            return Response({"detail": "unit query param is required."}, status=400)

        term = AcademicTerm.objects.filter(is_current=True).first()
        if not term:
            return Response([])

        students_qs = StudentUnit.objects.select_related("user").filter(
            unit_id=unit_id, term=term
        )

        students_data = [
            {
                "id": str(su.user.id),
                "name": su.user.get_full_name(),
                "university_id": su.user.university_id or su.user.username,
                "email": su.user.email,
            }
            for su in students_qs
        ]

        return Response(students_data)

class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        return Response({"detail": "Password reset email sent."})

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)

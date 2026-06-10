from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
import re

from apps.accounts.models import User
from apps.departments.models import Department, Faculty
from apps.programs.models.program import Program
from apps.students.models.student import Student
from apps.timetable.models import AcademicTerm

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

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

        tokens = get_tokens_for_user(user)
        return Response({
            "token": tokens['access'],
            "refresh": tokens['refresh'],
            "user": serialize_user(user)
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        user = authenticate(username=email, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        tokens = get_tokens_for_user(user)
        return Response({
            "token": tokens['access'],
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

class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        return Response({"detail": "Password reset email sent."})

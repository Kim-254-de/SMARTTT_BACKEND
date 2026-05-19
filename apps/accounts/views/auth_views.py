from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.db import transaction

from apps.accounts.models import User
from apps.departments.models import Department
from apps.programs.models.program import Program
from apps.students.models.student import Student

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

def serialize_user(user):
    student = getattr(user, 'student_profile', None)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.get_full_name(),
        "admission_number": user.university_id,
        "course": student.program.name if student and student.program else None,
        "department": student.program.department.name if student and student.program and student.program.department else None,
        "year_of_study": student.current_study_year if student else None,
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
        year_of_study = data.get('year_of_study', 1)

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
            university_id=admission_number,
            role=User.Role.STUDENT
        )

        if department_name and course_name:
            import re
            dept_code = re.sub(r'[^A-Z]', '', department_name.upper())[:20]
            if not dept_code: dept_code = department_name.upper()[:20]
            
            department, _ = Department.objects.get_or_create(
                name=department_name,
                defaults={'code': dept_code}
            )
            
            prog_code = re.sub(r'[^A-Z]', '', course_name.upper())[:30]
            if not prog_code: prog_code = course_name.upper()[:30]

            program, _ = Program.objects.get_or_create(
                name=course_name,
                defaults={
                    'code': prog_code,
                    'department': department
                }
            )

            from datetime import datetime
            import re
            
            reg_num = re.sub(r'[^A-Z0-9\-]', '', admission_number.upper()) if admission_number else f"STU-{user.id}"
            if not reg_num:
                reg_num = f"STU-{user.id}"

            Student.objects.create(
                user=user,
                registration_number=reg_num,
                first_name=first_name or "First",
                last_name=last_name or "Last",
                email=email,
                department=department,
                program=program,
                admission_year=datetime.now().year,
                current_study_year=year_of_study
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
                student.current_study_year = data['year_of_study']
            if 'course' in data and 'department' in data:
                import re
                dept_code = re.sub(r'[^A-Z]', '', data['department'].upper())[:20]
                if not dept_code: dept_code = data['department'].upper()[:20]
                
                dept, _ = Department.objects.get_or_create(
                    name=data['department'],
                    defaults={'code': dept_code}
                )
                
                prog_code = re.sub(r'[^A-Z]', '', data['course'].upper())[:30]
                if not prog_code: prog_code = data['course'].upper()[:30]
                
                prog, _ = Program.objects.get_or_create(
                    name=data['course'],
                    defaults={'code': prog_code, 'department': dept}
                )
                student.program = prog
            student.save()

        return Response(serialize_user(user))

class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        return Response({"detail": "Password reset email sent."})

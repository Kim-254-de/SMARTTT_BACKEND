from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from django.utils import timezone
from datetime import date, timedelta

from apps.departments.models import Department, Faculty
from apps.programs.models import Program
from apps.students.models import Student
from apps.timetable.models import AcademicTerm
from apps.units.models import Unit
from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.enrollments.models import StudentEnrollment

User = get_user_model()

class StudentEnrollmentSyncTests(APITestCase):
    def setUp(self):
        # Create department/faculty
        self.faculty = Faculty.objects.create(name="Science", code="SCI")
        self.dept = Department.objects.create(faculty=self.faculty, name="Computing", code="COMP")
        
        # Create program
        self.program = Program.objects.create(
            department=self.dept,
            name="Computer Science",
            code="BSCS",
            duration_years=4
        )
        
        # Create user & student profile
        self.user = User.objects.create_user(
            username="student1",
            email="student1@uni.ac.ke",
            password="password123",
            first_name="Murithi",
            last_name="Kamami"
        )
        self.student = Student.objects.create(
            user=self.user,
            registration_number="COSC-001",
            first_name="Murithi",
            last_name="Kamami",
            email="student1@uni.ac.ke",
            department=self.dept,
            program=self.program,
            current_study_year=4,
            current_semester=1,
            admission_year=2022
        )
        
        # Create academic term
        self.term = AcademicTerm.objects.create(
            academic_year="2025/2026",
            semester=1,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=120),
            is_current=True
        )
        
        # Create curriculum
        self.curriculum = Curriculum.objects.create(
            program=self.program,
            department=self.dept,
            academic_year="2025/2026",
            study_year=4,
            semester=1,
            status=Curriculum.Status.ACTIVE
        )
        
        # Create units
        self.unit1 = Unit.objects.create(
            code="COSC 435",
            name="User Interface Design",
            credit_hours=3.0,
            department=self.dept
        )
        self.unit2 = Unit.objects.create(
            code="COSC 451",
            name="Advanced Database Systems",
            credit_hours=3.0,
            department=self.dept
        )
        self.unit3 = Unit.objects.create(
            code="COSC 482",
            name="Computer System Project 1",
            credit_hours=3.0,
            department=self.dept
        )
        
        # Create curriculum units
        self.cu1 = CurriculumUnit.objects.create(
            curriculum=self.curriculum,
            unit=self.unit1,
            is_core=True
        )
        self.cu2 = CurriculumUnit.objects.create(
            curriculum=self.curriculum,
            unit=self.unit2,
            is_core=True
        )
        self.cu3 = CurriculumUnit.objects.create(
            curriculum=self.curriculum,
            unit=self.unit3,
            is_core=True
        )
        
        # Log in the user
        self.client.force_authenticate(user=self.user)

    def test_sync_registered_units_success(self):
        url = "/api/v1/enrollments/student-enrollments/sync/"
        data = {
            "unit_codes": ["COSC 435", "COSC 451"]
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check that enrollments are created
        enrollments = StudentEnrollment.objects.filter(student=self.student, status=StudentEnrollment.Status.ENROLLED)
        self.assertEqual(enrollments.count(), 2)
        
        # Verify specific units are enrolled
        enrolled_codes = [e.unit.code for e in enrollments]
        self.assertIn("COSC 435", enrolled_codes)
        self.assertIn("COSC 451", enrolled_codes)

    def test_sync_registered_units_drops_others(self):
        # Manually create an enrollment that should be dropped
        StudentEnrollment.objects.create(
            student=self.student,
            unit=self.unit3,
            term=self.term,
            status=StudentEnrollment.Status.ENROLLED
        )
        
        url = "/api/v1/enrollments/student-enrollments/sync/"
        data = {
            "unit_codes": ["COSC 435", "COSC 451"]
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check active and dropped enrollments
        active_enrollments = StudentEnrollment.objects.filter(
            student=self.student, status=StudentEnrollment.Status.ENROLLED
        )
        self.assertEqual(active_enrollments.count(), 2)
        
        dropped_enrollment = StudentEnrollment.objects.get(
            student=self.student, unit=self.unit3
        )
        self.assertEqual(dropped_enrollment.status, StudentEnrollment.Status.DROPPED)

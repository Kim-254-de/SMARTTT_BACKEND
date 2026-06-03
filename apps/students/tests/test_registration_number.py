from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.departments.models import Faculty, Department
from apps.programs.models import Program
from apps.students.models import Student


class StudentRegistrationNumberTests(TestCase):
    def setUp(self):
        self.faculty = Faculty.objects.create(name="Test Faculty", code="TF")
        self.department = Department.objects.create(
            faculty=self.faculty, name="Computer Science", code="CS"
        )
        self.program = Program.objects.create(
            department=self.department,
            name="BSc Computer Science",
            code="BCS",
            duration_years=4,
        )

        self.user = User.objects.create_user(
            username="student@example.com",
            email="student@example.com",
            password="secret123",
            role=User.Role.STUDENT,
            university_id="U-001",
            first_name="Test",
            last_name="Student",
        )

    def test_registration_number_allows_slash_and_normalizes_uppercase(self):
        student = Student.objects.create(
            user=self.user,
            registration_number="Ebt1/09919/23",
            first_name="Test",
            last_name="Student",
            email=self.user.email,
            department=self.department,
            program=self.program,
            admission_year=2024,
            current_study_year=1,
            current_semester=1,
        )

        self.assertEqual(student.registration_number, "EBT1/09919/23")

    def test_registration_number_rejects_underscore(self):
        student = Student(
            user=self.user,
            registration_number="EBT1/09919_23",
            first_name="Test",
            last_name="Student",
            email=self.user.email,
            department=self.department,
            program=self.program,
            admission_year=2024,
            current_study_year=1,
            current_semester=1,
        )

        with self.assertRaises(ValidationError):
            student.full_clean()

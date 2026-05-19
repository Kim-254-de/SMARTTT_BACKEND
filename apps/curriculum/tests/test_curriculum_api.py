from datetime import date

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.departments.models import Department
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.students.models import Student
from apps.timetable.models import AcademicTerm
from apps.units.models import Unit


class CurriculumAPITestCase(APITestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Computer Science", code="CS")
        self.other_department = Department.objects.create(name="Business", code="BUS")

        self.program = Program.objects.create(
            name="BSc Computer Science",
            code="BCS",
            department=self.department,
            duration_years=4,
        )

        self.unit_1 = Unit.objects.create(
            title="Data Structures",
            code="CSC201",
            credit_hours=3,
            department=self.department,
        )
        self.unit_2 = Unit.objects.create(
            title="Algorithms",
            code="CSC202",
            credit_hours=3,
            department=self.department,
        )

        self.admin_user = User.objects.create_user(
            username="deptadmin",
            password="secret123",
            role=User.Role.ADMIN,
            university_id="ADM001",
        )
        Lecturer.objects.create(user=self.admin_user, department=self.department)

        self.student_user = User.objects.create_user(
            username="student1",
            password="secret123",
            role=User.Role.STUDENT,
            university_id="STD001",
        )
        self.student_profile = Student.objects.create(
            user=self.student_user,
            program=self.program,
            admission_year=2025,
            current_study_year=2,
            academic_status=Student.AcademicStatus.ACTIVE,
            registration_number="STD-001",
            first_name="Student",
            last_name="One",
            email="student1@uni.edu",
            department=self.department,
        )

        AcademicTerm.objects.create(
            academic_year="2025/2026",
            semester=1,
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 31),
            is_current=True,
        )

    def test_department_admin_can_create_curriculum(self):
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("curriculum-list-create")
        payload = {
            "program": str(self.program.id),
            "department": str(self.department.id),
            "academic_year": "2025/2026",
            "study_year": 2,
            "semester": 1,
            "version": 1,
            "status": "active",
            "units": [
                {
                    "unit": str(self.unit_1.id),
                    "is_core": True,
                    "is_elective": False,
                    "display_order": 1,
                    "credit_hours": 3,
                },
                {
                    "unit": str(self.unit_2.id),
                    "is_core": True,
                    "is_elective": False,
                    "display_order": 2,
                    "credit_hours": 3,
                },
            ],
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        curriculum = Curriculum.objects.get(id=response.data["id"])
        self.assertEqual(curriculum.curriculum_units.count(), 2)

    def test_student_units_endpoint_returns_auto_mapped_units(self):
        curriculum = Curriculum.objects.create(
            program=self.program,
            department=self.department,
            academic_year="2025/2026",
            study_year=2,
            semester=1,
            version=1,
            status=Curriculum.Status.ACTIVE,
            created_by=self.admin_user,
        )
        CurriculumUnit.objects.create(
            curriculum=curriculum,
            unit=self.unit_1,
            is_core=True,
            is_elective=False,
            display_order=1,
            credit_hours=3,
        )

        self.client.force_authenticate(user=self.student_user)
        url = reverse("curriculum-student-units")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["study_year"], 2)
        self.assertEqual(response.data["semester"], 1)
        self.assertEqual(len(response.data["units"]), 1)
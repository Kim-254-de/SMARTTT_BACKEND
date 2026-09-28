from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.departments.models import Department, Faculty
from apps.programs.models import Program
from apps.students.models import Student

KEY = "test-attendance-key"
URL = reverse("integrations-attendance-student")


@override_settings(ATTENDANCE_API_KEY=KEY)
class AttendanceStudentLookupTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.program = Program.objects.create(department=self.dept, name="BSc Computer Science", code="BSCCS")

    def _get(self, key=KEY, **params):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.get(URL, params, **headers)

    def _student(self, reg, first="Amina", last="Kamau", email="amina@students.tharaka.ac.ke", profile_status=None, **user_kw):
        user = User.objects.create_user(username=reg, password="x", role=User.Role.STUDENT, university_id=reg,
                                        first_name=first, last_name=last, email=email, **user_kw)
        if profile_status:
            Student.objects.create(user=user, registration_number=reg, program=self.program, department=self.dept,
                                   admission_year=2023, first_name=first, last_name=last, email=email,
                                   current_study_year=3, academic_status=profile_status)
        return user

    def test_requires_the_api_key(self):
        self._student("EBT1/08223/23")
        self.assertEqual(self._get(key=None, registration_number="EBT1/08223/23").status_code, 403)
        self.assertEqual(self._get(key="wrong", registration_number="EBT1/08223/23").status_code, 403)

    def test_returns_the_student_record_case_insensitively(self):
        self._student("EBT1/08223/23", profile_status="active")
        res = self._get(registration_number="ebt1/08223/23")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {
            "registration_number": "EBT1/08223/23", "full_name": "Amina Kamau",
            "email": "amina@students.tharaka.ac.ke", "programme": "BSc Computer Science",
            "year_of_study": 3, "is_active": True,
        })

    def test_account_without_a_profile_still_found(self):
        self._student("EBT1/00001/23", first="Brian", last="Otieno", email="")
        res = self._get(registration_number="EBT1/00001/23")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["full_name"], "Brian Otieno")
        self.assertIsNone(res.data["email"])
        self.assertIsNone(res.data["programme"])
        self.assertTrue(res.data["is_active"])

    def test_graduated_or_disabled_students_are_not_active(self):
        self._student("EBT1/00002/20", email="a@x.com", profile_status="graduated")
        self._student("EBT1/00003/23", email="b@x.com", is_active=False)
        self.assertFalse(self._get(registration_number="EBT1/00002/20").data["is_active"])
        self.assertFalse(self._get(registration_number="EBT1/00003/23").data["is_active"])

    def test_found_by_profile_registration_number_when_login_id_differs(self):
        user = self._student("LOGIN-ID-1", email="c@x.com")
        Student.objects.create(user=user, registration_number="EBT1/00004/23", program=self.program, department=self.dept,
                               admission_year=2023, first_name="Cynthia", last_name="Ouma", email="c@x.com")
        res = self._get(registration_number="EBT1/00004/23")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["registration_number"], "LOGIN-ID-1")

    def test_lecturers_are_not_students(self):
        User.objects.create_user(username="lec", password="x", role=User.Role.LECTURER, university_id="STF/0001")
        self.assertEqual(self._get(registration_number="STF/0001").status_code, 404)

    def test_unknown_or_missing_number(self):
        self.assertEqual(self._get(registration_number="EBT1/99999/23").status_code, 404)
        self.assertEqual(self._get().status_code, 400)

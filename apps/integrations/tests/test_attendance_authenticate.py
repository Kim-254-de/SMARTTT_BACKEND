from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User, ValidStaffID
from apps.departments.models import Department, Faculty
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.students.models import Student

KEY = "test-attendance-key"
URL = reverse("integrations-attendance-authenticate")
PASSWORD = "correct horse"


@override_settings(ATTENDANCE_API_KEY=KEY)
class AttendanceAuthenticateTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.program = Program.objects.create(department=self.dept, name="BSc Computer Science", code="BSCCS")

    def _post(self, identifier, password=PASSWORD, key=KEY):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.post(URL, {"identifier": identifier, "password": password}, format="json", **headers)

    def _student(self, reg="EBT1/08223/23", email="amina@students.tharaka.ac.ke", profile=True, **user_kw):
        user = User.objects.create_user(username=email, email=email, password=PASSWORD, role=User.Role.STUDENT,
                                        university_id=reg, first_name="Amina", last_name="Kamau", **user_kw)
        if profile:
            Student.objects.create(user=user, registration_number=reg, program=self.program, department=self.dept,
                                   admission_year=2023, first_name="Amina", last_name="Kamau", email=email,
                                   current_study_year=3, academic_status="active")
        return user

    def _lecturer(self, staff="STF/0001", listed=True):
        if listed:
            ValidStaffID.objects.create(staff_id=staff, is_claimed=True)
        user = User.objects.create_user(username="pk@tharaka.ac.ke", email="pk@tharaka.ac.ke", password=PASSWORD,
                                        role=User.Role.LECTURER, university_id=staff,
                                        first_name="Peter", last_name="Kamami")
        Lecturer.objects.create(user=user, department=self.dept, rank="Dr.")
        return user

    def test_requires_the_api_key(self):
        self._student()
        self.assertEqual(self._post("EBT1/08223/23", key=None).status_code, 403)
        self.assertEqual(self._post("EBT1/08223/23", key="wrong").status_code, 403)

    def test_requires_an_identifier_and_a_password(self):
        self.assertEqual(self._post("", PASSWORD).status_code, 400)
        self.assertEqual(self._post("EBT1/08223/23", "").status_code, 400)

    def test_a_student_signs_in_with_their_admission_number_or_email(self):
        user = self._student()
        for identifier in ("ebt1/08223/23", "AMINA@students.tharaka.ac.ke"):
            res = self._post(identifier)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data["authenticated"], True)
            self.assertEqual(res.data["account"], {
                "id": str(user.id), "role": "student", "university_id": "EBT1/08223/23",
                "email": "amina@students.tharaka.ac.ke", "full_name": "Amina Kamau",
                "is_admin": False,
            })
            self.assertEqual(res.data["student"], {
                "registration_number": "EBT1/08223/23", "full_name": "Amina Kamau",
                "email": "amina@students.tharaka.ac.ke", "programme": "BSc Computer Science",
                "year_of_study": 3, "is_active": True,
            })
            self.assertIsNone(res.data["staff"])

    def test_a_lecturer_signs_in_with_their_staff_id(self):
        self._lecturer()
        res = self._post("stf/0001")
        self.assertEqual(res.data["authenticated"], True)
        self.assertEqual(res.data["account"]["role"], "lecturer")
        self.assertEqual(res.data["staff"]["staff_number"], "STF/0001")
        self.assertEqual(res.data["staff"]["department"], "Computer Science")
        self.assertIsNone(res.data["student"])

    def test_a_lecturer_removed_from_the_staff_list_has_no_staff_record(self):
        self._lecturer(listed=False)
        res = self._post("STF/0001")
        self.assertEqual(res.data["authenticated"], True)
        self.assertIsNone(res.data["staff"])

    def test_wrong_password_or_unknown_account_is_not_authenticated(self):
        # A 200, not a 401: the attendance backend must never confuse this with its key being refused.
        self._student()
        for identifier, password in (("EBT1/08223/23", "wrong"), ("EBT1/99999/23", PASSWORD), ("nobody@x.com", PASSWORD)):
            res = self._post(identifier, password)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.data, {"authenticated": False})

    def test_a_disabled_account_is_not_authenticated(self):
        self._student(is_active=False)
        self.assertEqual(self._post("EBT1/08223/23").data, {"authenticated": False})

    def test_a_google_only_account_has_no_password_to_check(self):
        User.objects.create_user(username="g@gmail.com", email="g@gmail.com", password=None, role=User.Role.STUDENT)
        self.assertEqual(self._post("g@gmail.com", "anything").data, {"authenticated": False})

    def test_a_student_without_an_admission_number_has_no_student_record(self):
        User.objects.create_user(username="new@x.com", email="new@x.com", password=PASSWORD, role=User.Role.STUDENT)
        res = self._post("new@x.com")
        self.assertEqual(res.data["authenticated"], True)
        self.assertIsNone(res.data["account"]["university_id"])
        self.assertIsNone(res.data["student"])

    def test_a_staff_account_is_an_administrator(self):
        User.objects.create_user(username="registry@tharaka.ac.ke", email="registry@tharaka.ac.ke", password=PASSWORD,
                                 role=User.Role.ADMIN, is_staff=True, first_name="Grace", last_name="Mwangi")
        res = self._post("REGISTRY@tharaka.ac.ke")
        self.assertEqual(res.data["authenticated"], True)
        self.assertIs(res.data["account"]["is_admin"], True)
        self.assertIsNone(res.data["student"])
        self.assertIsNone(res.data["staff"])

    def test_a_lecturer_with_staff_rights_stays_a_lecturer(self):
        user = self._lecturer()
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        self.assertIs(self._post("STF/0001").data["account"]["is_admin"], False)

    def test_an_admin_role_without_staff_rights_is_not_an_administrator(self):
        User.objects.create_user(username="clerk@tharaka.ac.ke", email="clerk@tharaka.ac.ke", password=PASSWORD,
                                 role=User.Role.ADMIN, is_staff=False)
        self.assertIs(self._post("clerk@tharaka.ac.ke").data["account"]["is_admin"], False)

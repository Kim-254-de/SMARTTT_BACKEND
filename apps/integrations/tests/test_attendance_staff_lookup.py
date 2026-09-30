from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User, ValidStaffID
from apps.departments.models import Department, Faculty
from apps.lecturers.models import Lecturer

KEY = "test-attendance-key"
URL = reverse("integrations-attendance-staff")


@override_settings(ATTENDANCE_API_KEY=KEY)
class AttendanceStaffLookupTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")

    def _get(self, key=KEY, **params):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.get(URL, params, **headers)

    def test_requires_the_api_key(self):
        ValidStaffID.objects.create(staff_id="STF/0001")
        self.assertEqual(self._get(key=None, staff_number="STF/0001").status_code, 403)
        self.assertEqual(self._get(key="wrong", staff_number="STF/0001").status_code, 403)

    def test_requires_a_staff_number(self):
        self.assertEqual(self._get().status_code, 400)

    def test_listed_staff_id_without_an_account_uses_the_csv_name(self):
        ValidStaffID.objects.create(staff_id="STF/0001", name_hint="Peter Kamami")
        res = self._get(staff_number="stf/0001")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {
            "staff_number": "STF/0001", "full_name": "Peter Kamami", "email": None,
            "department": None, "faculty": None, "title": None,
            "has_account": False, "is_active": True,
        })

    def test_listed_staff_id_with_an_account_uses_the_account(self):
        ValidStaffID.objects.create(staff_id="STF/0002", name_hint="P. Kamami", is_claimed=True)
        user = User.objects.create_user(username="pk@tharaka.ac.ke", email="PK@tharaka.ac.ke", password="x",
                                        role=User.Role.LECTURER, university_id="STF/0002",
                                        first_name="Peter", last_name="Kamami")
        Lecturer.objects.create(user=user, department=self.dept, rank="Dr.")
        res = self._get(staff_number="STF/0002")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, {
            "staff_number": "STF/0002", "full_name": "Peter Kamami", "email": "pk@tharaka.ac.ke",
            "department": "Computer Science", "faculty": "Science", "title": "Dr.",
            "has_account": True, "is_active": True,
        })

    def test_unlisted_staff_number_is_not_found_even_with_an_account(self):
        # The approved list is the authority: an account alone doesn't count.
        User.objects.create_user(username="x@tharaka.ac.ke", password="x", role=User.Role.LECTURER, university_id="STF/0003")
        self.assertEqual(self._get(staff_number="STF/0003").status_code, 404)
        self.assertEqual(self._get(staff_number="STF/9999").status_code, 404)

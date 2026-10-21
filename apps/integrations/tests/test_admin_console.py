from datetime import date

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User, ValidStaffID
from apps.departments.models import Department, Faculty
from apps.timetable.models import AcademicTerm

KEY = "test-attendance-key"


@override_settings(ATTENDANCE_API_KEY=KEY)
class ActingAdminTests(APITestCase):
    """integrations/admin/: SMARTTT's admin views, called by the console for a signed-in administrator."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="registry@tharaka.ac.ke", email="registry@tharaka.ac.ke", password="x",
            role=User.Role.ADMIN, is_staff=True, is_superuser=True,
        )
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 1), end_date=date(2026, 12, 18),
        )
        AcademicTerm.objects.create(
            academic_year="2025/2026", semester=3, start_date=date(2026, 5, 4), end_date=date(2026, 8, 21), is_current=True,
        )

    def _call(self, method, name, acting=None, key=KEY, **kwargs):
        headers = {}
        if key is not None:
            headers["HTTP_X_API_KEY"] = key
        if acting is not None:
            headers["HTTP_X_ACTING_ACCOUNT"] = str(acting)
        url = reverse(name, kwargs=kwargs.pop("url_kwargs", None))
        return getattr(self.client, method)(url, format="json", **headers, **kwargs)

    def test_a_wrong_or_missing_key_is_401(self):
        for key in (None, "wrong"):
            res = self._call("get", "admin-terms", acting=self.admin.id, key=key)
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.data["code"], "invalid_api_key")

    def test_the_acting_account_must_be_an_administrator(self):
        lecturer = User.objects.create_user(username="pk", email="pk@tharaka.ac.ke", password="x",
                                            role=User.Role.LECTURER, is_staff=True, university_id="STF/0001")
        ValidStaffID.objects.create(staff_id="STF/0001", is_claimed=True)
        inactive = User.objects.create_user(username="gone", email="gone@tharaka.ac.ke", password="x",
                                            role=User.Role.ADMIN, is_staff=True, is_active=False)
        for acting in (None, "not-a-uuid", "6f1c1e8e-2a43-4f7b-9a0e-1d8d7d2b3c4f", lecturer.id, inactive.id):
            res = self._call("get", "admin-terms", acting=acting)
            self.assertEqual(res.status_code, 403, acting)
            self.assertEqual(res.data["code"], "not_admin")

    def test_an_administrator_manages_terms(self):
        res = self._call("get", "admin-terms", acting=self.admin.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 2)

        res = self._call("post", "admin-term-set-current", acting=self.admin.id, url_kwargs={"pk": self.term.pk})
        self.assertEqual(res.status_code, 200)
        self.term.refresh_from_db()
        self.assertTrue(self.term.is_current)
        self.assertEqual(AcademicTerm.objects.filter(is_current=True).count(), 1)

    def test_smarttts_own_rules_still_apply_to_a_staff_account(self):
        # Staff, but not a superuser or registrar: SMARTTT lets them read terms,
        # not change the current one. That is a refusal, never a crash.
        staff = User.objects.create_user(username="clerk@tharaka.ac.ke", email="clerk@tharaka.ac.ke", password="x",
                                         role=User.Role.ADMIN, is_staff=True)
        self.assertEqual(self._call("get", "admin-terms", acting=staff.id).status_code, 200)
        res = self._call("post", "admin-term-set-current", acting=staff.id, url_kwargs={"pk": self.term.pk})
        self.assertEqual(res.status_code, 403)

    def test_an_administrator_reaches_every_admin_function(self):
        for name in ("admin-timetable-upload-list", "admin-notifications", "admin-staff-ids",
                     "admin-staff-id-uploads", "admin-rooms-capacity", "admin-programs"):
            res = self._call("get", name, acting=self.admin.id)
            self.assertEqual(res.status_code, 200, name)

    def test_a_jwt_does_not_open_the_console_routes(self):
        # Only the key and an acting administrator get in here, never a user token.
        self.client.force_authenticate(user=None)
        res = self.client.get(reverse("admin-terms"))
        self.assertEqual(res.status_code, 401)


@override_settings(ATTENDANCE_API_KEY=KEY)
class DirectoryTests(APITestCase):
    """attendance/faculties/ and attendance/departments/: SMARTTT owns them, attendance links to them."""

    FACULTIES = reverse("integrations-attendance-faculties")
    DEPARTMENTS = reverse("integrations-attendance-departments")

    def _post(self, url, body, key=KEY):
        return self.client.post(url, body, format="json", **({"HTTP_X_API_KEY": key} if key else {}))

    def test_requires_the_api_key(self):
        self.assertEqual(self.client.get(self.FACULTIES).status_code, 403)
        self.assertEqual(self._post(self.FACULTIES, {"name": "Science"}, key="wrong").status_code, 403)

    def test_a_faculty_is_created_with_a_code_from_its_name(self):
        Faculty.objects.create(name="Faculty of Education", code="FS")
        res = self._post(self.FACULTIES, {"name": "  Faculty of   Science "})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["name"], "Faculty of Science")
        self.assertEqual(res.data["code"], "FS2")

        listed = self.client.get(self.FACULTIES, HTTP_X_API_KEY=KEY).data["faculties"]
        self.assertEqual([f["name"] for f in listed], ["Faculty of Education", "Faculty of Science"])

    def test_a_taken_name_answers_with_the_existing_id(self):
        faculty = Faculty.objects.create(name="Science", code="SCI")
        res = self._post(self.FACULTIES, {"name": "science"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data, {"detail": "That name is already in use.", "code": "name_taken", "id": faculty.id})

    def test_a_department_is_created_in_its_faculty(self):
        faculty = Faculty.objects.create(name="Science", code="SCI")
        res = self._post(self.DEPARTMENTS, {"faculty_id": faculty.id, "name": "Department of Computer Science"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["faculty_id"], faculty.id)
        self.assertEqual(res.data["code"], "DCS")
        self.assertTrue(Department.objects.filter(name="Department of Computer Science", faculty=faculty).exists())

        again = self._post(self.DEPARTMENTS, {"faculty_id": faculty.id, "name": "department of computer science"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.data["id"], res.data["id"])

    def test_a_department_needs_a_known_faculty(self):
        for faculty_id in (None, "abc", 999):
            res = self._post(self.DEPARTMENTS, {"faculty_id": faculty_id, "name": "Physics"})
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.data["code"], "unknown_faculty")

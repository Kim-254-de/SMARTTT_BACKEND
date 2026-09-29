from datetime import date

from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.timetable.models import AcademicTerm


class SetCurrentTermTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", role=User.Role.ADMIN, university_id="ADM1", is_staff=True, is_superuser=True)
        self.old = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=2, start_date=date(2026, 1, 5), end_date=date(2026, 4, 30), is_current=True,
        )
        self.new = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 1), end_date=date(2026, 12, 18),
        )

    def url(self, term):
        return f"/api/v1/timetable/terms/{term.pk}/set-current/"

    def test_admin_sets_current_term_and_unsets_previous(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url(self.new))

        self.assertEqual(response.status_code, 200)
        self.new.refresh_from_db()
        self.old.refresh_from_db()
        self.assertTrue(self.new.is_current)
        self.assertFalse(self.old.is_current)

    def test_requires_authentication(self):
        response = self.client.post(self.url(self.new))

        self.assertIn(response.status_code, (401, 403))
        self.new.refresh_from_db()
        self.assertFalse(self.new.is_current)

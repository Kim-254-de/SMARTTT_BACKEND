from django.test import TestCase
from apps.departments.models import Department


class DepartmentModelTests(TestCase):
    def test_create_department_without_a_faculty(self):
        d = Department.objects.create(name="Test Dept", code="TD")
        self.assertEqual(str(d), "Test Dept (TD)")

    def test_codes_are_unique_across_the_university(self):
        from django.db import IntegrityError

        Department.objects.create(name="Test Dept", code="TD")
        with self.assertRaises(IntegrityError):
            Department.objects.create(name="Other Dept", code="TD")

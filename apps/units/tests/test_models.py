from django.test import TestCase
from apps.departments.models import Department
from apps.units.models import Unit


class UnitModelTests(TestCase):
    def test_unit_creation(self):
        d = Department.objects.create(name="D2", code="D2")
        u = Unit.objects.create(department=d, code="U1", name="Intro", credit_hours=3.0)
        self.assertEqual(str(u), "Intro (U1)")

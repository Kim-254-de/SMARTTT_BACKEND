from django.test import TestCase
from apps.departments.models import Department
from apps.programs.models import Program


class ProgramModelTests(TestCase):
    def test_program_creation(self):
        d = Department.objects.create(name="D", code="D1")
        p = Program.objects.create(department=d, name="BSc Test", code="BSC-TEST", duration_years=3)
        self.assertEqual(str(p), "BSc Test (BSC-TEST)")

from django.test import TestCase
from apps.departments.models import Faculty, Department
from apps.programs.models import Program
from apps.units.models import Unit
from apps.curriculum.models.models import Curriculum, CurriculumUnit


class CurriculumTests(TestCase):
    def test_curriculum_units(self):
        f = Faculty.objects.create(name="F", code="FC")
        d = Department.objects.create(faculty=f, name="D", code="DC")
        p = Program.objects.create(department=d, name="P", code="PC", duration_years=3)
        u = Unit.objects.create(department=d, code="U1", name="Unit 1", credit_hours=3.0)
        c = Curriculum.objects.create(program=p, department=d, academic_year="2025/2026", study_year=2, semester=1, version=1)
        cu = CurriculumUnit.objects.create(curriculum=c, unit=u, is_core=True, display_order=1)
        self.assertIn(u, [x.unit for x in c.curriculum_units.all()])

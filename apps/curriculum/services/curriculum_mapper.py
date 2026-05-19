from apps.curriculum.models.models import Curriculum, CurriculumUnit


class CurriculumMapper:
    @staticmethod
    def fetch_curriculum(program, study_year, semester, academic_year=None, active_only=True):
        qs = Curriculum.objects.filter(program=program, study_year=study_year, semester=semester)
        if academic_year:
            qs = qs.filter(academic_year=academic_year)
        if active_only:
            qs = qs.filter(status="active")
        # prefer latest version
        qs = qs.order_by("-version")
        return qs.first()

    @staticmethod
    def units_for_curriculum(curriculum):
        if not curriculum:
            return CurriculumUnit.objects.none()
        return curriculum.units.select_related("unit").all()

    @staticmethod
    def determine_units_for_student(program, study_year, semester, academic_year=None):
        curriculum = CurriculumMapper.fetch_curriculum(program, study_year, semester, academic_year=academic_year)
        units = CurriculumMapper.units_for_curriculum(curriculum)
        return [cu.unit for cu in units]
from django.core.exceptions import ValidationError

from apps.curriculum.models import Curriculum
from apps.timetable.models import AcademicTerm


class CurriculumMapperService:
    """Resolves curriculum structures and required student units."""

    @staticmethod
    def get_curriculum(*, program_id, study_year: int, semester: int, academic_year: str | None = None):
        queryset = Curriculum.objects.filter(
            program_id=program_id,
            study_year=study_year,
            semester=semester,
            status=Curriculum.Status.ACTIVE,
        ).select_related("program", "department")

        if academic_year:
            queryset = queryset.filter(academic_year=academic_year)

        return queryset.order_by("-version").first()

    @classmethod
    def get_required_units_for_student(cls, *, student):
        if not student:
            raise ValidationError("Student profile is required.")

        current_term = AcademicTerm.objects.filter(is_current=True).order_by("-academic_year").first()
        if not current_term:
            raise ValidationError("No active academic term found.")

        curriculum = cls.get_curriculum(
            program_id=student.program_id,
            study_year=student.current_study_year,
            semester=current_term.semester,
            academic_year=current_term.academic_year,
        )
        if not curriculum:
            raise ValidationError(
                "No active curriculum found for the student's program/year/semester."
            )

        units = curriculum.curriculum_units.select_related("unit", "prerequisite_unit").order_by(
            "display_order", "unit__code"
        )

        return {
            "student_id": str(student.id),
            "program_id": str(student.program_id),
            "academic_year": curriculum.academic_year,
            "study_year": curriculum.study_year,
            "semester": curriculum.semester,
            "curriculum_id": str(curriculum.id),
            "curriculum_version": curriculum.version,
            "units": [
                {
                    "curriculum_unit_id": str(item.id),
                    "unit_id": str(item.unit_id),
                    "unit_code": item.unit.code,
                    "unit_title": item.unit.title,
                    "credit_hours": item.credit_hours,
                    "is_core": item.is_core,
                    "is_elective": item.is_elective,
                    "display_order": item.display_order,
                    "prerequisite_unit_id": str(item.prerequisite_unit_id)
                    if item.prerequisite_unit_id
                    else None,
                    "prerequisite_unit_code": item.prerequisite_unit.code
                    if item.prerequisite_unit_id
                    else None,
                }
                for item in units
            ],
        }
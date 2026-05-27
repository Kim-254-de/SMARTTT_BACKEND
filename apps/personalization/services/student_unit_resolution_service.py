"""Resolve the student's applicable units."""

from __future__ import annotations

from dataclasses import dataclass

from apps.personalization.selectors import PersonalizationSelector
from apps.personalization.validators import PersonalizationValidator


@dataclass(frozen=True)
class ResolvedStudentUnits:
	source: str
	academic_year: str
	semester: int
	curriculum: object | None
	enrollment_queryset: object
	unit_queryset: object
	unit_ids: list[str]


class PersonalizedUnitsResolutionError(Exception):
	"""Raised when units cannot be resolved for personalization."""


class StudentUnitResolutionService:
	"""Resolve units from enrollment first, then curriculum fallback."""

	@staticmethod
	def resolve_student_units(student) -> ResolvedStudentUnits:
		PersonalizationValidator.validate_student(student)
		academic_year = student.academic_year_string
		semester = PersonalizationValidator.validate_semester(student.current_semester)

		enrollment_queryset = PersonalizationSelector.get_enrolled_unit_enrollments(
			student,
			academic_year=academic_year,
			semester=semester,
		)

		if enrollment_queryset.exists():
			unit_ids = list(
				enrollment_queryset.values_list("unit_id", flat=True)
			)
			return ResolvedStudentUnits(
				source="enrollment",
				academic_year=academic_year,
				semester=semester,
				curriculum=None,
				enrollment_queryset=enrollment_queryset,
				unit_queryset=enrollment_queryset,
				unit_ids=[str(unit_id) for unit_id in unit_ids],
			)

		return ResolvedStudentUnits(
			source="enrollment",
			academic_year=academic_year,
			semester=semester,
			curriculum=None,
			enrollment_queryset=enrollment_queryset,
			unit_queryset=enrollment_queryset,
			unit_ids=[],
		)

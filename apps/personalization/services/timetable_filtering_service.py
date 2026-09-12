"""Filter timetable sessions for a student context."""

from __future__ import annotations

from apps.personalization.selectors import PersonalizationSelector


class TimetableFilteringService:
	"""Database-driven timetable filtering supporting multi-tier group and combination matching."""

	@staticmethod
	def get_personalized_sessions(student, unit_ids: list[str], academic_year: str, semester: int):
		return PersonalizationSelector.get_matching_sessions(
			unit_ids=unit_ids,
			program_id=str(student.program_id),
			study_year=student.current_study_year,
			semester=semester,
			academic_year=academic_year,
			combination=getattr(student, 'combination', None),
			timetable_group=getattr(student, 'timetable_group', None),
		)

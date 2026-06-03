"""Database selectors for personalization queries."""

from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from apps.curriculum.models import Curriculum, CurriculumUnit
from apps.enrollments.models import StudentEnrollment as UnitEnrollment
from apps.students.models import Student
from apps.timetable.models import TimetableSession


class PersonalizationSelector:
	"""Optimized read queries for personalization flows."""

	@staticmethod
	def get_student_by_user_id(user_id: str) -> Optional[Student]:
		return (
			Student.objects.select_related("user", "department", "program", "program__department")
			.filter(user_id=user_id)
			.first()
		)

	@staticmethod
	def get_student_by_id(student_id: str) -> Optional[Student]:
		return (
			Student.objects.select_related("user", "department", "program", "program__department")
			.filter(id=student_id)
			.first()
		)

	@staticmethod
	def get_current_curriculum(student: Student) -> Optional[Curriculum]:
		return (
			Curriculum.objects.select_related("program", "department")
			.filter(
				program=student.program,
				study_year=student.current_study_year,
				semester=student.current_semester,
				status=Curriculum.Status.ACTIVE,
			)
			.order_by("-version", "-created_at")
			.first()
		)

	@staticmethod
	def get_enrolled_unit_enrollments(
		student: Student,
		academic_year: str,
		semester: int,
	) -> QuerySet:
		return (
			UnitEnrollment.objects.select_related(
				"student",
				"term",
				"unit",
			)
			.filter(
				student_id=student.id,
				status=UnitEnrollment.Status.ENROLLED,
				term__academic_year=academic_year,
				term__semester=semester,
			)
			.order_by("unit__code")
		)

	@staticmethod
	def get_curriculum_units(curriculum: Curriculum) -> QuerySet:
		return (
			CurriculumUnit.objects.select_related(
				"curriculum",
				"unit",
				"prerequisite_unit",
			)
			.filter(curriculum=curriculum)
			.order_by("display_order", "unit__code")
		)

	@staticmethod
	def get_matching_sessions(
		unit_ids,
		program_id: str,
		study_year: int,
		semester: int,
		academic_year: str,
	) -> QuerySet:
		return (
			TimetableSession.objects.select_related(
				"unit",
				"unit__department",
				"program",
				"department",
				"lecturer",
				"lecturer__user",
				"room",
				"time_slot",
				"created_by",
			)
			.filter(
				unit_id__in=unit_ids,
				program_id=program_id,
				study_year=study_year,
				semester=semester,
				academic_year=academic_year,
				status__in=[
					TimetableSession.Status.SCHEDULED,
					TimetableSession.Status.ACTIVE,
				],
			)
			.order_by("day_of_week", "time_slot__start_time", "unit__code")
		)

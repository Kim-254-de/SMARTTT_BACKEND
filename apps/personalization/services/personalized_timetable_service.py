"""Build the final personalized timetable payload."""

from __future__ import annotations

from apps.personalization.services.personalization_cache_service import PersonalizationCacheService
from apps.personalization.services.student_unit_resolution_service import StudentUnitResolutionService
from apps.personalization.services.timetable_filtering_service import TimetableFilteringService
from apps.personalization.services.timetable_sorting_service import TimetableSortingService
from apps.personalization.utils import serialize_unit


class PersonalizedTimetableService:
    """Coordinate student resolution, filtering, sorting, deduplication, and response shaping."""

    @staticmethod
    def generate_personalized_timetable(student, use_cache: bool = False) -> dict:
        resolved = StudentUnitResolutionService.resolve_student_units(student)

        if use_cache:
            cached = PersonalizationCacheService.get(str(student.id), resolved.academic_year, resolved.semester)
            if cached is not None:
                return cached

        sessions = TimetableFilteringService.get_personalized_sessions(
            student=student,
            unit_ids=resolved.unit_ids,
            academic_year=resolved.academic_year,
            semester=resolved.semester,
        )

        # Deduplicate multiple upload copies of the same class
        seen_keys = set()
        deduped_sessions = []
        for s in sessions:
            unit_id = str(getattr(s, "unit_id", ""))
            day = getattr(s, "day_of_week", "")
            slot_id = str(getattr(s, "time_slot_id", ""))
            room_id = str(getattr(s, "room_id", ""))

            # Unique key represents a distinct scheduled class
            key = (unit_id, day, slot_id, room_id)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_sessions.append(s)

        ordered_sessions = TimetableSortingService.sort_sessions(deduped_sessions)
        grouped_timetable = TimetableSortingService.group_sessions(ordered_sessions)

        payload = {
            "student": {
                "id": str(student.id),
                "registration_number": student.registration_number,
                "full_name": student.get_full_name(),
                "program": {
                    "id": str(student.program_id),
                    "code": student.program.code,
                    "name": student.program.name,
                },
                "department_id": str(student.department_id),
                "study_year": student.current_study_year,
                "semester": resolved.semester,
                "academic_year": resolved.academic_year,
            },
            "source": resolved.source,
            "academic_context": {
                "study_year": student.current_study_year,
                "semester": resolved.semester,
                "academic_year": resolved.academic_year,
                "program_id": str(student.program_id),
                "department_id": str(student.department_id),
            },
            "units": [
                serialize_unit(enrollment.unit)
                for enrollment in resolved.enrollment_queryset
            ]
            if resolved.source == "enrollment"
            else [serialize_unit(enrollment.unit) for enrollment in resolved.unit_queryset],
            "timetable": grouped_timetable,
            "summary": {
                "unit_count": len(resolved.unit_ids),
                "session_count": len(ordered_sessions),
                "has_enrollment_data": resolved.source == "enrollment",
            },
        }

        if use_cache:
            PersonalizationCacheService.set(str(student.id), resolved.academic_year, resolved.semester, payload)

        return payload

    @staticmethod
    def generate_student_units_payload(student) -> dict:
        resolved = StudentUnitResolutionService.resolve_student_units(student)
        units = (
            [serialize_unit(enrollment.unit) for enrollment in resolved.enrollment_queryset]
            if resolved.source == "enrollment"
            else [serialize_unit(enrollment.unit) for enrollment in resolved.unit_queryset]
        )

        return {
            "student": {
                "id": str(student.id),
                "registration_number": student.registration_number,
                "full_name": student.get_full_name(),
                "program": {
                    "id": str(student.program_id),
                    "code": student.program.code,
                    "name": student.program.name,
                },
                "department_id": str(student.department_id),
                "study_year": student.current_study_year,
                "semester": resolved.semester,
                "academic_year": resolved.academic_year,
            },
            "source": resolved.source,
            "units": units,
            "summary": {
                "unit_count": len(units),
                "has_enrollment_data": resolved.source == "enrollment",
            },
        }

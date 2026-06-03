"""
Service layer for timetable management.

Orchestrates business logic:
- TimetableSessionService: Create, update, retrieve sessions
- TimetableFilterService: Fetch personalized timetables
- RoomAllocationService: Manage room assignments
- LecturerScheduleService: Manage lecturer teaching schedules
- TimetableConflictService: Detect and report conflicts
"""

from django.db import models, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, F, Sum
from rest_framework.exceptions import ValidationError

from apps.timetable.models import TimetableSession, Room, TimeSlot
from apps.timetable.selectors import TimetableSessionSelector, RoomSelector, TimeSlotSelector
from apps.timetable.validators import TimetableSessionValidator, ConflictValidator
from apps.curriculum.models import CurriculumUnit
from apps.units.models import Unit


class TimetableSessionService:
    """
    Orchestrate timetable session operations.

    Responsibilities:
    - Create sessions with validation
    - Update sessions
    - Retrieve sessions with optimization
    - Manage session status
    """

    @staticmethod
    @transaction.atomic
    def create_session(
        unit_id: str,
        program_id: str,
        department_id: str,
        lecturer_id: str,
        room_id: str,
        time_slot_id: str,
        academic_year: str,
        study_year: int,
        semester: int,
        day_of_week: str,
        session_type: str,
        delivery_mode: str,
        student_group: str,
        max_students: int,
        created_by,
        notes: str = "",
    ) -> TimetableSession:
        """
        Create a new timetable session with comprehensive validation.

        Args:
            unit_id: Unit to be taught
            program_id: Program offering session
            department_id: Department managing session
            lecturer_id: Lecturer teaching session
            room_id: Room where session occurs
            time_slot_id: Time slot for session
            academic_year: Academic year (YYYY/YYYY)
            study_year: Year of study (1-5)
            semester: Semester (1 or 2)
            day_of_week: Day of week
            session_type: Type of session (lecture, practical, etc.)
            delivery_mode: How session is delivered (face-to-face, online, etc.)
            student_group: Student group identifier
            max_students: Maximum students
            created_by: User creating the session
            notes: Additional notes

        Returns:
            Created TimetableSession instance

        Raises:
            ValidationError: If any validation fails
        """
        # Validate all business rules
        TimetableSessionValidator.validate_semester(semester)
        TimetableSessionValidator.validate_study_year(study_year)
        TimetableSessionValidator.validate_academic_year_format(academic_year)
        TimetableSessionValidator.validate_max_students(max_students)
        TimetableSessionValidator.validate_time_slot_validity(time_slot_id)
        TimetableSessionValidator.validate_room_capacity(room_id, max_students)

        # Check for conflicts
        TimetableSessionValidator.validate_session_uniqueness(
            unit_id, program_id, study_year, semester, day_of_week, time_slot_id, student_group, academic_year
        )
        TimetableSessionValidator.validate_room_conflict(
            room_id, day_of_week, time_slot_id, academic_year, semester
        )
        TimetableSessionValidator.validate_lecturer_conflict(
            lecturer_id, day_of_week, time_slot_id, academic_year, semester
        )

        # Create session
        session = TimetableSession.objects.create(
            unit_id=unit_id,
            program_id=program_id,
            department_id=department_id,
            lecturer_id=lecturer_id,
            room_id=room_id,
            time_slot_id=time_slot_id,
            academic_year=academic_year,
            study_year=study_year,
            semester=semester,
            day_of_week=day_of_week,
            session_type=session_type,
            delivery_mode=delivery_mode,
            student_group=student_group,
            max_students=max_students,
            created_by=created_by,
            notes=notes,
            status="scheduled",
        )

        return session

    @staticmethod
    @transaction.atomic
    def update_session(
        session_id: str,
        **kwargs,
    ) -> TimetableSession:
        """
        Update a timetable session with validation.

        Args:
            session_id: Session ID to update
            **kwargs: Fields to update

        Returns:
            Updated TimetableSession instance
        """
        session = TimetableSessionSelector.get_session_by_id(session_id)

        # If updating conflicting fields, validate
        if "day_of_week" in kwargs or "time_slot_id" in kwargs or "room_id" in kwargs or "lecturer_id" in kwargs:
            day = kwargs.get("day_of_week", session.day_of_week)
            time_slot = kwargs.get("time_slot_id", str(session.time_slot_id))
            room = kwargs.get("room_id", str(session.room_id) if session.room else None)
            lecturer = kwargs.get("lecturer_id", str(session.lecturer_id) if session.lecturer else None)

            TimetableSessionValidator.validate_room_conflict(
                room, day, time_slot, session.academic_year, session.semester, session_id
            )
            TimetableSessionValidator.validate_lecturer_conflict(
                lecturer, day, time_slot, session.academic_year, session.semester, session_id
            )

        # If updating max_students, validate room capacity
        if "max_students" in kwargs:
            new_max = kwargs["max_students"]
            room_id = kwargs.get("room_id", str(session.room_id) if session.room else None)
            TimetableSessionValidator.validate_max_students(new_max)
            TimetableSessionValidator.validate_room_capacity(room_id, new_max)

        # Update fields
        for field, value in kwargs.items():
            setattr(session, field, value)

        session.full_clean()
        session.save()

        return session

    @staticmethod
    def get_session(session_id: str) -> TimetableSession:
        """Get single session with optimized queries."""
        return TimetableSessionSelector.get_session_by_id(session_id)

    @staticmethod
    def list_sessions(
        academic_year: str = None,
        semester: int = None,
        status: str = None,
        **filters,
    ):
        """Get list of sessions with optional filters."""
        return TimetableSessionSelector.get_all_sessions(
            academic_year=academic_year,
            semester=semester,
            status=status,
        )

    @staticmethod
    @transaction.atomic
    def activate_session(session_id: str) -> TimetableSession:
        """Mark session as active."""
        return TimetableSessionService.update_session(session_id, status="active")

    @staticmethod
    @transaction.atomic
    def complete_session(session_id: str) -> TimetableSession:
        """Mark session as completed."""
        return TimetableSessionService.update_session(session_id, status="completed")

    @staticmethod
    @transaction.atomic
    def cancel_session(session_id: str, reason: str = "") -> TimetableSession:
        """Cancel a session."""
        session = TimetableSessionService.update_session(session_id, status="cancelled", notes=reason)
        return session

    @staticmethod
    @transaction.atomic
    def enroll_student_in_session(session_id: str) -> TimetableSession:
        """
        Increment student enrollment in session.

        Args:
            session_id: Session ID

        Returns:
            Updated session

        Raises:
            ValidationError: If session is full
        """
        session = TimetableSessionSelector.get_session_by_id(session_id)

        if session.is_full:
            raise ValidationError({"current_enrollment": "Session is at maximum capacity"})

        session.current_enrollment += 1
        session.save()

        return session

    @staticmethod
    @transaction.atomic
    def withdraw_student_from_session(session_id: str) -> TimetableSession:
        """
        Decrement student enrollment in session.

        Args:
            session_id: Session ID

        Returns:
            Updated session
        """
        session = TimetableSessionSelector.get_session_by_id(session_id)

        if session.current_enrollment > 0:
            session.current_enrollment -= 1
            session.save()

        return session


class TimetableFilterService:
    """
    Generate personalized timetables for students.

    Filters timetable sessions based on:
    - Student program
    - Curriculum units for study year/semester
    - Academic year and semester
    """

    @staticmethod
    def get_student_timetable(student, academic_year: str, semester: int):
        """
        Get personalized timetable for a student.

        Dynamic filtering based on:
        Student → Program → Curriculum → Units → TimetableSessions

        Args:
            student: Student instance
            academic_year: Academic year
            semester: Semester

        Returns:
            Queryset of timetable sessions for student
        """
        # Check for explicitly enrolled units first
        from apps.enrollments.models import StudentEnrollment
        enrollments = StudentEnrollment.objects.filter(
            student=student,
            term__academic_year=academic_year,
            term__semester=semester,
            status=StudentEnrollment.Status.ENROLLED
        )
        if enrollments.exists():
            unit_ids = enrollments.values_list("unit_id", flat=True)
            return TimetableSession.objects.filter(
                unit_id__in=unit_ids,
                academic_year=academic_year,
                semester=semester
            )

        # Fallback to curriculum-based filtering
        # Get student's program and study year
        program = student.program
        study_year = student.current_study_year

        # Get sessions for this program/year/semester
        sessions = TimetableSessionSelector.get_sessions_by_program(
            program_id=str(program.id),
            academic_year=academic_year,
            study_year=study_year,
            semester=semester,
        )

        # Filter to only units in curriculum
        curriculum = student.get_current_curriculum()
        if curriculum:
            curriculum_unit_ids = curriculum.curriculum_units.values_list("unit_id", flat=True)
            sessions = sessions.filter(unit_id__in=curriculum_unit_ids)

        return sessions

    @staticmethod
    def get_filtered_timetable_by_day(sessions, day_of_week: str):
        """Filter sessions by day of week."""
        return sessions.filter(day_of_week=day_of_week)

    @staticmethod
    def get_filtered_timetable_by_session_type(sessions, session_type: str):
        """Filter sessions by type (lecture, lab, etc.)."""
        return sessions.filter(session_type=session_type)

    @staticmethod
    def get_timetable_statistics(sessions):
        """Get statistics about timetable sessions."""
        return {
            "total_sessions": sessions.count(),
            "total_credit_hours": sessions.aggregate(total=Sum("unit__credit_hours"))["total"] or 0,
            "sessions_by_day": sessions.values("day_of_week").annotate(count=Count("id")),
            "sessions_by_type": sessions.values("session_type").annotate(count=Count("id")),
        }


class RoomAllocationService:
    """
    Manage room assignments and occupancy.

    Responsibilities:
    - Validate room assignments
    - Detect room conflicts
    - Report room occupancy
    """

    @staticmethod
    def get_room_schedule(room_id: str, day_of_week: str = None, academic_year: str = None):
        """
        Get room schedule (all sessions in room).

        Args:
            room_id: Room ID
            day_of_week: Optional day filter
            academic_year: Optional academic year filter

        Returns:
            Queryset of sessions in room
        """
        return TimetableSessionSelector.get_sessions_by_room(
            room_id, day_of_week, academic_year
        )

    @staticmethod
    def check_room_availability(
        room_id: str,
        day_of_week: str,
        time_slot_id: str,
        academic_year: str,
        semester: int,
    ) -> bool:
        """
        Check if room is available for a time slot.

        Args:
            room_id: Room ID
            day_of_week: Day of week
            time_slot_id: Time slot ID
            academic_year: Academic year
            semester: Semester

        Returns:
            True if available, False otherwise
        """
        conflicting = TimetableSessionSelector.get_sessions_by_day_and_slot(
            day_of_week, time_slot_id, academic_year, semester
        ).filter(room_id=room_id, status__in=["scheduled", "active"])

        return not conflicting.exists()

    @staticmethod
    def get_room_occupancy_report(room_id: str, academic_year: str = None):
        """Get occupancy statistics for a room."""
        sessions = RoomAllocationService.get_room_schedule(room_id, academic_year=academic_year)

        total_capacity_slots = sessions.count()
        total_students = sessions.aggregate(total=Sum("current_enrollment"))["total"] or 0

        return {
            "room_id": room_id,
            "total_sessions": total_capacity_slots,
            "total_enrolled_students": total_students,
            "average_occupancy": (total_students / total_capacity_slots * 100)
            if total_capacity_slots > 0
            else 0,
        }

    @staticmethod
    def get_available_rooms(
        capacity_needed: int,
        day_of_week: str,
        time_slot_id: str,
        academic_year: str,
        semester: int,
    ) -> models.QuerySet:
        """
        Find available rooms meeting criteria.

        Args:
            capacity_needed: Minimum capacity needed
            day_of_week: Day of week
            time_slot_id: Time slot ID
            academic_year: Academic year
            semester: Semester

        Returns:
            Queryset of available rooms
        """
        available_rooms = RoomSelector.get_rooms_by_capacity(capacity_needed)

        # Filter out rooms with conflicts
        conflicting_room_ids = (
            TimetableSessionSelector.get_sessions_by_day_and_slot(
                day_of_week, time_slot_id, academic_year, semester
            )
            .values_list("room_id", flat=True)
            .distinct()
        )

        return available_rooms.exclude(id__in=conflicting_room_ids)


class LecturerScheduleService:
    """
    Manage lecturer teaching schedules.

    Responsibilities:
    - Get lecturer teaching schedule
    - Check lecturer availability
    - Detect lecturer conflicts
    """

    @staticmethod
    def get_lecturer_schedule(
        lecturer_id: str,
        academic_year: str = None,
        semester: int = None,
    ):
        """Get all sessions assigned to lecturer."""
        return TimetableSessionSelector.get_sessions_by_lecturer(
            lecturer_id, academic_year, semester
        )

    @staticmethod
    def check_lecturer_availability(
        lecturer_id: str,
        day_of_week: str,
        time_slot_id: str,
        academic_year: str,
        semester: int,
    ) -> bool:
        """
        Check if lecturer is available for time slot.

        Args:
            lecturer_id: Lecturer ID
            day_of_week: Day of week
            time_slot_id: Time slot ID
            academic_year: Academic year
            semester: Semester

        Returns:
            True if available, False otherwise
        """
        conflicting = TimetableSessionSelector.get_sessions_by_day_and_slot(
            day_of_week, time_slot_id, academic_year, semester
        ).filter(lecturer_id=lecturer_id, status__in=["scheduled", "active"])

        return not conflicting.exists()

    @staticmethod
    def get_lecturer_workload(
        lecturer_id: str,
        academic_year: str,
        semester: int,
    ):
        """
        Get lecturer workload statistics.

        Args:
            lecturer_id: Lecturer ID
            academic_year: Academic year
            semester: Semester

        Returns:
            Dictionary with workload statistics
        """
        sessions = LecturerScheduleService.get_lecturer_schedule(
            lecturer_id, academic_year, semester
        )

        total_sessions = sessions.count()
        total_hours = sessions.aggregate(total=Sum("time_slot__duration_minutes"))[
            "total"
        ] or 0
        total_hours_formatted = total_hours / 60  # Convert minutes to hours

        return {
            "lecturer_id": lecturer_id,
            "academic_year": academic_year,
            "semester": semester,
            "total_sessions": total_sessions,
            "total_teaching_hours": total_hours_formatted,
            "sessions_by_program": (
                sessions.values("program__name")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
        }


class TimetableConflictService:
    """
    Detect and report scheduling conflicts.

    Detects:
    - Room conflicts (double-booking)
    - Lecturer conflicts (schedule overlap)
    - Overlapping time slots
    """

    @staticmethod
    def detect_conflicts(
        day_of_week: str,
        time_slot_id: str,
        room_id: str = None,
        lecturer_id: str = None,
        academic_year: str = None,
        semester: int = None,
        session_id: str = None,
    ) -> list:
        """
        Detect all conflicts for a potential session.

        Args:
            day_of_week: Day of week
            time_slot_id: Time slot ID
            room_id: Room ID (optional)
            lecturer_id: Lecturer ID (optional)
            academic_year: Academic year
            semester: Semester
            session_id: Exclude this session (for updates)

        Returns:
            List of conflicts detected
        """
        return ConflictValidator.check_for_conflicts(
            day_of_week, time_slot_id, room_id, lecturer_id, academic_year, semester, session_id
        )

    @staticmethod
    def get_conflict_report(
        academic_year: str,
        semester: int,
        department_id: str = None,
    ):
        """
        Generate comprehensive conflict report.

        Args:
            academic_year: Academic year
            semester: Semester
            department_id: Optional department filter

        Returns:
            Dictionary with conflict statistics
        """
        sessions = TimetableSessionSelector.get_all_sessions(
            academic_year=academic_year,
            semester=semester,
        )

        if department_id:
            sessions = sessions.filter(department_id=department_id)

        conflicts = []

        # Check each session for conflicts
        for session in sessions:
            session_conflicts = TimetableConflictService.detect_conflicts(
                session.day_of_week,
                str(session.time_slot_id),
                str(session.room_id) if session.room else None,
                str(session.lecturer_id) if session.lecturer else None,
                academic_year,
                semester,
                str(session.id),
            )

            if session_conflicts:
                conflicts.extend(session_conflicts)

        return {
            "academic_year": academic_year,
            "semester": semester,
            "total_sessions": sessions.count(),
            "conflicts_found": len(conflicts),
            "conflicts": conflicts,
        }

    @staticmethod
    def suggest_alternative_slots(
        day_of_week: str,
        time_slot_id: str,
        room_id: str = None,
        lecturer_id: str = None,
        academic_year: str = None,
        semester: int = None,
    ) -> list:
        """
        Suggest alternative time slots to resolve conflicts.

        Args:
            day_of_week: Original day
            time_slot_id: Original time slot
            room_id: Room to schedule in
            lecturer_id: Lecturer to schedule
            academic_year: Academic year
            semester: Semester

        Returns:
            List of alternative time slots
        """
        all_slots = TimeSlotSelector.get_all_active_slots()
        alternative_slots = []

        for slot in all_slots:
            is_available = LecturerScheduleService.check_lecturer_availability(
                lecturer_id, day_of_week, str(slot.id), academic_year, semester
            )

            if room_id:
                is_available = is_available and RoomAllocationService.check_room_availability(
                    room_id, day_of_week, str(slot.id), academic_year, semester
                )

            if is_available:
                alternative_slots.append(
                    {
                        "slot_id": str(slot.id),
                        "time_range": f"{slot.start_time} - {slot.end_time}",
                        "duration_minutes": slot.duration_minutes,
                    }
                )

        return alternative_slots

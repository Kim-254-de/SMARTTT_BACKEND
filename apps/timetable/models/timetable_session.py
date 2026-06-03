from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib.postgres.fields import ArrayField

from apps.common.models import BaseModel


class TimetableSession(BaseModel):
    """
    Core model representing a scheduled teaching session in the timetable.

    A timetable session is the actual scheduling instance that combines:
    - What: Unit being taught
    - When: Day of week and time slot
    - Where: Room/venue
    - Who: Lecturer teaching
    - For whom: Student group/cohort

    Key Design:
    - Sessions link to Units (not Programs directly)
    - Personalized student timetables are generated dynamically
    - Students do NOT have direct timetable ownership
    - Instead: Student → Program → Curriculum → Units → TimetableSessions
    - This enables curriculum-driven dynamic timetable generation
    """

    class DayOfWeek(models.TextChoices):
        """Day of week choices."""

        MONDAY = "MON", _("Monday")
        TUESDAY = "TUE", _("Tuesday")
        WEDNESDAY = "WED", _("Wednesday")
        THURSDAY = "THU", _("Thursday")
        FRIDAY = "FRI", _("Friday")
        SATURDAY = "SAT", _("Saturday")
        SUNDAY = "SUN", _("Sunday")

    class SessionType(models.TextChoices):
        """Type of teaching session."""

        LECTURE = "lecture", _("Lecture")
        PRACTICAL = "practical", _("Practical/Lab")
        TUTORIAL = "tutorial", _("Tutorial")
        SEMINAR = "seminar", _("Seminar")
        WORKSHOP = "workshop", _("Workshop")
        PROJECT = "project", _("Project")
        FIELD_WORK = "field_work", _("Field Work")

    class DeliveryMode(models.TextChoices):
        """How the session is delivered."""

        FACE_TO_FACE = "face_to_face", _("Face-to-Face")
        ONLINE = "online", _("Online")
        HYBRID = "hybrid", _("Hybrid")
        BLENDED = "blended", _("Blended")

    class Status(models.TextChoices):
        """Session operational status."""

        SCHEDULED = "scheduled", _("Scheduled")
        ACTIVE = "active", _("Active")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        SUSPENDED = "suspended", _("Suspended")

    # Core relationships
    unit = models.ForeignKey(
        "units.Unit",
        on_delete=models.CASCADE,
        related_name="timetable_sessions",
        help_text=_("Unit/course being taught in this session"),
    )
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.CASCADE,
        related_name="timetable_sessions",
        help_text=_("Program this session is offered under (enables filtering)"),
    )
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.CASCADE,
        related_name="timetable_sessions",
        help_text=_("Department offering this session"),
    )
    lecturer = models.ForeignKey(
        "lecturers.Lecturer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_sessions",
        help_text=_("Lecturer assigned to teach this session"),
    )
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_sessions",
        help_text=_("Room/venue where session occurs"),
    )
    time_slot = models.ForeignKey(
        "timetable.TimeSlot",
        on_delete=models.PROTECT,
        related_name="timetable_sessions",
        help_text=_("Time slot for this session"),
    )

    # Academic context
    academic_year = models.CharField(
        max_length=10,
        help_text=_("Academic year (e.g., 2024/2025)"),
    )
    study_year = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1, 6)],
        help_text=_("Year of study (1-5)"),
    )
    semester = models.PositiveSmallIntegerField(
        choices=[(1, _("Semester 1")), (2, _("Semester 2"))],
        help_text=_("Semester (1 or 2)"),
    )

    # Scheduling details
    day_of_week = models.CharField(
        max_length=3,
        choices=DayOfWeek.choices,
        help_text=_("Day when class occurs"),
    )
    session_type = models.CharField(
        max_length=20,
        choices=SessionType.choices,
        default=SessionType.LECTURE,
        help_text=_("Type of teaching session"),
    )
    delivery_mode = models.CharField(
        max_length=20,
        choices=DeliveryMode.choices,
        default=DeliveryMode.FACE_TO_FACE,
        help_text=_("How session is delivered"),
    )

    # Student group management
    student_group = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Student group/cohort identifier (e.g., Group A, Set 1)"),
    )
    max_students = models.PositiveSmallIntegerField(
        help_text=_("Maximum number of students for this session"),
    )
    current_enrollment = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Current enrolled students"),
    )

    # Status and metadata
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        help_text=_("Current session status"),
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_timetable_sessions",
        help_text=_("User who created this session"),
    )
    notes = models.TextField(
        blank=True,
        help_text=_("Additional notes or instructions for the session"),
    )

    class Meta:
        db_table = "timetable_session"
        indexes = [
            models.Index(fields=["academic_year", "semester"]),
            models.Index(fields=["program", "study_year", "semester"]),
            models.Index(fields=["department", "day_of_week"]),
            models.Index(fields=["lecturer", "day_of_week"]),
            models.Index(fields=["room", "day_of_week"]),
            models.Index(fields=["day_of_week", "time_slot"]),
            models.Index(fields=["status"]),
            models.Index(fields=["unit"]),
        ]
        verbose_name = _("Timetable Session")
        verbose_name_plural = _("Timetable Sessions")
        ordering = ["day_of_week", "time_slot__start_time"]
        unique_together = [
            ["unit", "program", "study_year", "semester", "day_of_week", "time_slot", "student_group", "academic_year"],
        ]

    def __str__(self) -> str:
        return (
            f"{self.unit.code} - {self.day_of_week} "
            f"{self.time_slot.start_time.strftime('%H:%M')} "
            f"@ {self.room.code if self.room else 'TBA'}"
        )

    def clean(self):
        """Model-level validation."""
        # Validate semester
        if self.semester not in [1, 2]:
            raise ValidationError(
                _("Semester must be 1 or 2"),
                code="invalid_semester",
            )

        # Validate study year
        if not (1 <= self.study_year <= 5):
            raise ValidationError(
                _("Study year must be between 1 and 5"),
                code="invalid_study_year",
            )

        # Validate room capacity
        if self.room and self.max_students > self.room.capacity:
            raise ValidationError(
                _(
                    f"Max students ({self.max_students}) cannot exceed "
                    f"room capacity ({self.room.capacity})"
                ),
                code="exceeds_room_capacity",
            )

        # Validate current enrollment
        if self.current_enrollment > self.max_students:
            raise ValidationError(
                _(f"Current enrollment ({self.current_enrollment}) exceeds max students ({self.max_students})"),
                code="enrollment_exceeds_maximum",
            )

        # Unit and program must be from same department
        if self.unit.department_id != self.department_id:
            raise ValidationError(
                _("Unit's department must match session's department"),
                code="department_mismatch",
            )

        # Lecturer must be from same department
        if self.lecturer and self.lecturer.department_id != self.department_id:
            raise ValidationError(
                _("Lecturer must be from the same department"),
                code="lecturer_department_mismatch",
            )

    @property
    def is_full(self) -> bool:
        """Check if session is at maximum capacity."""
        return self.current_enrollment >= self.max_students

    @property
    def available_seats(self) -> int:
        """Get number of available seats."""
        return max(0, self.max_students - self.current_enrollment)

    @property
    def occupancy_percentage(self) -> float:
        """Get occupancy percentage."""
        if self.max_students == 0:
            return 0.0
        return (self.current_enrollment / self.max_students) * 100

    def can_enroll_student(self) -> bool:
        """Check if a student can be enrolled in this session."""
        return not self.is_full and self.status in [
            self.Status.SCHEDULED,
            self.Status.ACTIVE,
        ]

    def get_session_time_str(self) -> str:
        """Get formatted session time string."""
        start = self.time_slot.start_time.strftime("%H:%M")
        end = self.time_slot.end_time.strftime("%H:%M")
        return f"{start}-{end}"

    def get_day_display(self) -> str:
        """Get day name."""
        return self.get_day_of_week_display()

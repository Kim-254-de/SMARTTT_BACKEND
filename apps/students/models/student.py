from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    RegexValidator,
    URLValidator,
)
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class Student(BaseModel):
    """
    Core Student model representing an academic identity in the university.
    
    Every student belongs to:
    - A user account (authentication/authorization)
    - A department (organizational unit)
    - An academic program (curriculum)
    - A faculty (parent of department)
    
    Used for:
    - Personalized timetable generation
    - Curriculum mapping
    - Academic progress tracking
    - Role-based access control
    """

    class Gender(models.TextChoices):
        MALE = "male", _("Male")
        FEMALE = "female", _("Female")
        OTHER = "other", _("Other")
        PREFER_NOT_TO_SAY = "prefer_not_to_say", _("Prefer not to say")

    class AcademicStatus(models.TextChoices):
        ACTIVE = "active", _("Active")
        INACTIVE = "inactive", _("Inactive")
        SUSPENDED = "suspended", _("Suspended")
        GRADUATED = "graduated", _("Graduated")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        ON_LEAVE = "on_leave", _("On Leave")

    class EnrollmentType(models.TextChoices):
        FULL_TIME = "full_time", _("Full Time")
        PART_TIME = "part_time", _("Part Time")
        DISTANCE_LEARNING = "distance_learning", _("Distance Learning")
        SANDWICH = "sandwich", _("Sandwich")
        BLOCK_RELEASE = "block_release", _("Block Release")

    # User Link - One-to-One relationship with User
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="student_profile",
        help_text=_("Link to user account for authentication"),
    )

    # Academic Identity
    registration_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Unique student registration number (e.g., STU2024001)"),
        validators=[
            RegexValidator(
                regex=r"^[A-Z0-9\-]+$",
                message=_("Registration number must contain only uppercase letters, numbers, and hyphens"),
                code="invalid_registration_number",
            )
        ],
    )

    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        default=Gender.PREFER_NOT_TO_SAY,
    )
    email = models.EmailField(unique=True, db_index=True)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\+?1?\d{9,15}$",
                message=_("Phone number must be valid international format"),
                code="invalid_phone_number",
            )
        ],
    )
    date_of_birth = models.DateField(null=True, blank=True)

    # Academic Organization
    faculty = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="faculty_students",
        help_text=_("Faculty/College the student belongs to"),
    )
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="students",
        help_text=_("Department offering the student's program"),
    )
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="enrolled_students",
        help_text=_("Academic program the student is enrolled in"),
    )

    # Academic Progress
    current_study_year = models.PositiveSmallIntegerField(
        default=1,
        validators=[],  # Validate in clean()
        help_text=_("Current year of study (1-based)"),
    )
    current_semester = models.PositiveSmallIntegerField(
        default=1,
        validators=[],  # Validate in clean()
        help_text=_("Current semester (1-based)"),
    )
    admission_year = models.PositiveIntegerField(
        help_text=_("Year of admission (e.g., 2024)"),
    )

    # Status and Enrollment
    academic_status = models.CharField(
        max_length=20,
        choices=AcademicStatus.choices,
        default=AcademicStatus.ACTIVE,
        db_index=True,
        help_text=_("Current academic status"),
    )
    enrollment_type = models.CharField(
        max_length=20,
        choices=EnrollmentType.choices,
        default=EnrollmentType.FULL_TIME,
        help_text=_("Type of enrollment"),
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text=_("Whether the student is currently active"),
    )

    # Media
    profile_photo = models.ImageField(
        upload_to="students/photos/%Y/%m/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif"])
        ],
        help_text=_("Student profile photograph"),
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["registration_number"]
        indexes = [
            models.Index(fields=["registration_number"]),
            models.Index(fields=["email"]),
            models.Index(fields=["department", "program"]),
            models.Index(fields=["academic_status", "is_active"]),
            models.Index(fields=["admission_year"]),
            models.Index(fields=["current_study_year", "current_semester"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["registration_number"],
                name="uq_student_registration_number",
            ),
            models.UniqueConstraint(
                fields=["email"],
                name="uq_student_email",
            ),
            models.CheckConstraint(
                check=models.Q(current_study_year__gte=1),
                name="ck_student_current_study_year_positive",
            ),
            models.CheckConstraint(
                check=models.Q(current_semester__gte=1),
                name="ck_student_current_semester_positive",
            ),
            models.CheckConstraint(
                check=models.Q(admission_year__gte=1900),
                name="ck_student_admission_year_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.registration_number} - {self.get_full_name()}"

    def get_full_name(self) -> str:
        """Return student's full name."""
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self) -> None:
        """Validate student data."""
        super().clean()

        # Validate current study year
        if self.current_study_year < 1:
            raise ValidationError({
                "current_study_year": _("Study year must be at least 1"),
            })

        # Validate against program duration
        if self.program:
            if self.current_study_year > self.program.duration_years:
                raise ValidationError({
                    "current_study_year": _(
                        f"Study year cannot exceed program duration of {self.program.duration_years} years"
                    ),
                })

        # Validate current semester
        if self.current_semester < 1 or self.current_semester > 2:
            raise ValidationError({
                "current_semester": _("Semester must be 1 or 2"),
            })

        # Validate admission year
        from django.utils import timezone
        current_year = timezone.now().year

        if self.admission_year > current_year:
            raise ValidationError({
                "admission_year": _("Admission year cannot be in the future"),
            })

        # Validate department belongs to program
        if self.program and self.program.department != self.department:
            raise ValidationError({
                "department": _(
                    "Selected department must be the same as the program's department"
                ),
            })

        # Email consistency check
        if self.user and self.email != self.user.email:
            raise ValidationError({
                "email": _("Student email must match user account email"),
            })

    def save(self, *args, **kwargs) -> None:
        """Save student with validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def academic_year_string(self) -> str:
        """Return current academic year string (e.g., '2024/2025')."""
        return f"{self.admission_year + self.current_study_year - 1}/{self.admission_year + self.current_study_year}"

    @property
    def is_graduated(self) -> bool:
        """Check if student has graduated."""
        return self.academic_status == self.AcademicStatus.GRADUATED

    @property
    def is_suspended(self) -> bool:
        """Check if student is suspended."""
        return self.academic_status == self.AcademicStatus.SUSPENDED

    def can_enroll_in_courses(self) -> bool:
        """Determine if student can enroll in courses."""
        return (
            self.is_active
            and self.academic_status == self.AcademicStatus.ACTIVE
            and not self.is_graduated
        )

    def get_current_curriculum(self):
        """Get curriculum for student's current study year/semester."""
        from apps.curriculum.models import Curriculum

        return Curriculum.objects.filter(
            program=self.program,
            study_year=self.current_study_year,
            semester=self.current_semester,
            status=Curriculum.Status.ACTIVE,
        ).first()

    def get_required_units(self):
        """Get units required by student's current curriculum."""
        curriculum = self.get_current_curriculum()
        if not curriculum:
            return []
        return curriculum.curriculum_units.all()


class AcademicProgress(BaseModel):
    """
    Tracks student academic performance over time.
    
    Records:
    - Semester-wise GPA and CGPA
    - Credit hours completed
    - Academic status changes
    """

    class Status(models.TextChoices):
        GOOD_STANDING = "good_standing", _("Good Standing")
        WARNING = "warning", _("Academic Warning")
        PROBATION = "probation", _("Academic Probation")
        SUSPENSION = "suspension", _("Suspension")
        DISMISSED = "dismissed", _("Dismissed")

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="academic_progress",
        help_text=_("Student whose progress this record tracks"),
    )

    academic_year = models.CharField(
        max_length=20,
        help_text=_("Academic year (e.g., '2024/2025')"),
        db_index=True,
    )
    study_year = models.PositiveSmallIntegerField(
        help_text=_("Year of study during this period"),
    )
    semester = models.PositiveSmallIntegerField(
        help_text=_("Semester during this period (1 or 2)"),
    )

    # Academic Metrics
    gpa = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.00,
        help_text=_("Semester GPA (0.00-4.00)"),
    )
    cgpa = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=0.00,
        help_text=_("Cumulative GPA (0.00-4.00)"),
    )
    total_credits = models.PositiveIntegerField(
        default=0,
        help_text=_("Total credit hours completed"),
    )
    credits_this_semester = models.PositiveIntegerField(
        default=0,
        help_text=_("Credit hours completed this semester"),
    )

    # Status
    academic_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.GOOD_STANDING,
        help_text=_("Academic standing for this period"),
    )

    # Metadata
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_academic_progress",
        help_text=_("User who recorded this progress"),
    )

    class Meta:
        ordering = ["-academic_year", "-study_year", "-semester"]
        indexes = [
            models.Index(fields=["student", "academic_year"]),
            models.Index(fields=["student", "-semester"]),
            models.Index(fields=["academic_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year", "study_year", "semester"],
                name="uq_academic_progress_student_period",
            ),
            models.CheckConstraint(
                check=models.Q(gpa__gte=0, gpa__lte=4),
                name="ck_academic_progress_gpa_range",
            ),
            models.CheckConstraint(
                check=models.Q(cgpa__gte=0, cgpa__lte=4),
                name="ck_academic_progress_cgpa_range",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.student.registration_number} - "
            f"{self.academic_year} (Y{self.study_year}S{self.semester}) "
            f"GPA: {self.gpa}"
        )

    def clean(self) -> None:
        """Validate academic progress data."""
        super().clean()

        if self.gpa < 0 or self.gpa > 4.0:
            raise ValidationError({
                "gpa": _("GPA must be between 0.00 and 4.00"),
            })

        if self.cgpa < 0 or self.cgpa > 4.0:
            raise ValidationError({
                "cgpa": _("CGPA must be between 0.00 and 4.00"),
            })

        if self.semester not in [1, 2]:
            raise ValidationError({
                "semester": _("Semester must be 1 or 2"),
            })

    def save(self, *args, **kwargs) -> None:
        """Save with validation."""
        self.full_clean()
        super().save(*args, **kwargs)


class StudentEnrollment(BaseModel):
    """
    Tracks student enrollment in curriculum for specific academic periods.
    
    Links:
    - Student
    - Curriculum
    - Semester/Year
    
    Used to track which students are following which curriculum
    """

    class EnrollmentStatus(models.TextChoices):
        ENROLLED = "enrolled", _("Enrolled")
        COMPLETED = "completed", _("Completed")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        FAILED = "failed", _("Failed")
        SUSPENDED = "suspended", _("Suspended")
        DEFERRED = "deferred", _("Deferred to Next Semester")

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments",
        help_text=_("Student enrolling in curriculum"),
    )
    curriculum = models.ForeignKey(
        "curriculum.Curriculum",
        on_delete=models.PROTECT,
        related_name="student_enrollments",
        help_text=_("Curriculum being enrolled in"),
    )

    academic_year = models.CharField(
        max_length=20,
        help_text=_("Academic year of enrollment"),
        db_index=True,
    )
    study_year = models.PositiveSmallIntegerField(
        help_text=_("Year of study"),
    )
    semester = models.PositiveSmallIntegerField(
        help_text=_("Semester (1 or 2)"),
    )

    enrollment_status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ENROLLED,
        db_index=True,
        help_text=_("Current enrollment status"),
    )
    enrollment_date = models.DateTimeField(
        auto_now_add=True,
        help_text=_("Date of enrollment"),
    )

    # Notes for withdrawals/deferrals
    notes = models.TextField(
        blank=True,
        help_text=_("Additional notes (e.g., reason for withdrawal)"),
    )

    class Meta:
        ordering = ["-academic_year", "-study_year", "-semester"]
        indexes = [
            models.Index(fields=["student", "academic_year"]),
            models.Index(fields=["curriculum", "academic_year"]),
            models.Index(fields=["enrollment_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "curriculum", "academic_year", "study_year", "semester"],
                name="uq_student_enrollment_period",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.student.registration_number} - "
            f"{self.curriculum.program.code} "
            f"({self.academic_year})"
        )

    def clean(self) -> None:
        """Validate enrollment data."""
        super().clean()

        if self.semester not in [1, 2]:
            raise ValidationError({
                "semester": _("Semester must be 1 or 2"),
            })

        # Ensure curriculum matches student's program and study year
        if self.curriculum:
            if self.curriculum.program != self.student.program:
                raise ValidationError({
                    "curriculum": _(
                        "Curriculum must belong to student's program"
                    ),
                })

            if self.curriculum.study_year != self.study_year:
                raise ValidationError({
                    "curriculum": _(
                        "Curriculum study year must match enrollment study year"
                    ),
                })

            if self.curriculum.semester != self.semester:
                raise ValidationError({
                    "curriculum": _(
                        "Curriculum semester must match enrollment semester"
                    ),
                })

    def save(self, *args, **kwargs) -> None:
        """Save with validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def is_active_enrollment(self) -> bool:
        """Check if enrollment is currently active."""
        return self.enrollment_status == self.EnrollmentStatus.ENROLLED

    def can_be_withdrawn(self) -> bool:
        """Check if enrollment can be withdrawn."""
        return self.enrollment_status in [
            self.EnrollmentStatus.ENROLLED,
            self.EnrollmentStatus.DEFERRED,
        ]


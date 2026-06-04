"""
Student selectors module.

Database query layer providing optimized, reusable queries
to prevent N+1 queries and reduce duplication.

Pattern: Selectors should be used for all read operations to
ensure consistent query optimization.
"""

from typing import List, Optional
from django.db.models import Q, Prefetch
from django.db.models.query import QuerySet

from apps.students.models import Student, AcademicProgress, StudentEnrollment


class StudentSelector:
    """Selectors for Student queries."""

    @staticmethod
    def get_student_list(
        filters: Optional[dict] = None,
        search: Optional[str] = None,
        ordering: str = "-created_at",
    ) -> QuerySet:
        """
        Get optimized list of students with filters and search.

        Args:
            filters: Dictionary of filter conditions
            search: Search term for registration_number, name, or email
            ordering: Field to order by

        Returns:
            QuerySet of students
        """
        queryset = Student.objects.select_related(
            "user",
            "department",
            "program",
        ).prefetch_related(
            "academic_progress",
            "enrollments",
        )

        # Apply filters
        if filters:
            if department_id := filters.get("department_id"):
                queryset = queryset.filter(department_id=department_id)
            if program_id := filters.get("program_id"):
                queryset = queryset.filter(program_id=program_id)
            if academic_status := filters.get("academic_status"):
                queryset = queryset.filter(academic_status=academic_status)
            if "is_active" in filters:
                queryset = queryset.filter(is_active=filters.get("is_active"))
            if admission_year := filters.get("admission_year"):
                queryset = queryset.filter(admission_year=admission_year)
            if current_study_year := filters.get("current_study_year"):
                queryset = queryset.filter(current_study_year=current_study_year)

        # Apply search
        if search:
            queryset = queryset.filter(
                Q(registration_number__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )

        return queryset.order_by(ordering).distinct()

    @staticmethod
    def get_student_by_id(student_id) -> Optional[Student]:
        """
        Get single student by ID with full details.

        Args:
            student_id: The student ID

        Returns:
            Student instance or None
        """
        return Student.objects.select_related(
            "user",
            "department",
            "program",
            "faculty",
        ).prefetch_related(
            "academic_progress",
            "enrollments__curriculum",
        ).filter(id=student_id).first()

    @staticmethod
    def get_student_by_registration_number(registration_number: str) -> Optional[Student]:
        """
        Get student by registration number.

        Args:
            registration_number: The registration number to search for

        Returns:
            Student instance or None
        """
        return Student.objects.select_related(
            "user",
            "department",
            "program",
        ).filter(registration_number=registration_number).first()

    @staticmethod
    def get_student_by_user_id(user_id) -> Optional[Student]:
        """
        Get student by user ID.

        Args:
            user_id: The user ID

        Returns:
            Student instance or None
        """
        return Student.objects.select_related(
            "user",
            "department",
            "program",
        ).filter(user_id=user_id).first()

    @staticmethod
    def get_students_by_department(department_id, active_only: bool = True) -> QuerySet:
        """
        Get all students in a department.

        Args:
            department_id: The department ID
            active_only: Filter to active students only

        Returns:
            QuerySet of students
        """
        queryset = Student.objects.filter(department_id=department_id).select_related(
            "user",
            "department",
            "program",
        )

        if active_only:
            queryset = queryset.filter(is_active=True, academic_status=Student.AcademicStatus.ACTIVE)

        return queryset

    @staticmethod
    def get_students_by_program(program_id, active_only: bool = True) -> QuerySet:
        """
        Get all students in a program.

        Args:
            program_id: The program ID
            active_only: Filter to active students only

        Returns:
            QuerySet of students
        """
        queryset = Student.objects.filter(program_id=program_id).select_related(
            "user",
            "department",
            "program",
        )

        if active_only:
            queryset = queryset.filter(is_active=True, academic_status=Student.AcademicStatus.ACTIVE)

        return queryset

    @staticmethod
    def get_students_by_year_and_semester(
        study_year: int,
        semester: int,
        department_id: Optional[int] = None,
        program_id: Optional[int] = None
    ) -> QuerySet:
        """
        Get students for a specific year and semester.

        Args:
            study_year: The year of study
            semester: The semester (1 or 2)
            department_id: Filter by department (optional)
            program_id: Filter by program (optional)

        Returns:
            QuerySet of students
        """
        queryset = Student.objects.filter(
            current_study_year=study_year,
            current_semester=semester,
            is_active=True,
        ).select_related(
            "user",
            "department",
            "program",
        )

        if department_id:
            queryset = queryset.filter(department_id=department_id)
        if program_id:
            queryset = queryset.filter(program_id=program_id)

        return queryset

    @staticmethod
    def get_active_students(department_id: Optional[int] = None) -> QuerySet:
        """
        Get all active students.

        Args:
            department_id: Filter by department (optional)

        Returns:
            QuerySet of active students
        """
        queryset = Student.objects.filter(
            is_active=True,
            academic_status=Student.AcademicStatus.ACTIVE
        ).select_related(
            "user",
            "department",
            "program",
        )

        if department_id:
            queryset = queryset.filter(department_id=department_id)

        return queryset

    @staticmethod
    def count_students_by_status(department_id: Optional[int] = None) -> dict:
        """
        Get count of students by academic status.

        Args:
            department_id: Filter by department (optional)

        Returns:
            Dictionary with status counts
        """
        queryset = Student.objects.all()

        if department_id:
            queryset = queryset.filter(department_id=department_id)

        return {
            status: queryset.filter(academic_status=status).count()
            for status, _ in Student.AcademicStatus.choices
        }


class AcademicProgressSelector:
    """Selectors for AcademicProgress queries."""

    @staticmethod
    def get_student_progress(student_id) -> QuerySet:
        """
        Get all academic progress records for a student.

        Args:
            student_id: The student ID

        Returns:
            Ordered QuerySet of progress records
        """
        return AcademicProgress.objects.filter(
            student_id=student_id
        ).select_related(
            "student",
            "recorded_by",
        ).order_by("-academic_year", "-semester")

    @staticmethod
    def get_latest_progress(student_id) -> Optional[AcademicProgress]:
        """
        Get most recent academic progress record.

        Args:
            student_id: The student ID

        Returns:
            Latest AcademicProgress or None
        """
        return AcademicProgress.objects.filter(
            student_id=student_id
        ).select_related(
            "student",
            "recorded_by",
        ).order_by("-academic_year", "-semester").first()

    @staticmethod
    def get_progress_by_period(
        student_id,
        academic_year: str,
        study_year: int,
        semester: int
    ) -> Optional[AcademicProgress]:
        """
        Get academic progress for specific period.

        Args:
            student_id: The student ID
            academic_year: The academic year
            study_year: The year of study
            semester: The semester

        Returns:
            AcademicProgress or None
        """
        return AcademicProgress.objects.filter(
            student_id=student_id,
            academic_year=academic_year,
            study_year=study_year,
            semester=semester
        ).first()

    @staticmethod
    def get_students_on_probation(department_id: Optional[int] = None) -> QuerySet:
        """
        Get students on academic probation.

        Args:
            department_id: Filter by department (optional)

        Returns:
            QuerySet of students on probation
        """
        queryset = AcademicProgress.objects.filter(
            academic_status=AcademicProgress.Status.PROBATION
        ).select_related(
            "student",
            "student__department",
            "student__program",
        ).distinct("student_id")

        if department_id:
            queryset = queryset.filter(student__department_id=department_id)

        return queryset


class StudentEnrollmentSelector:
    """Selectors for StudentEnrollment queries."""

    @staticmethod
    def get_student_enrollments(student_id) -> QuerySet:
        """
        Get all enrollments for a student.

        Args:
            student_id: The student ID

        Returns:
            QuerySet of enrollments
        """
        return StudentEnrollment.objects.filter(
            student_id=student_id
        ).select_related(
            "student",
            "curriculum",
            "curriculum__program",
        ).order_by("-academic_year", "-semester")

    @staticmethod
    def get_active_enrollment(student_id) -> Optional[StudentEnrollment]:
        """
        Get active enrollment for a student.

        Args:
            student_id: The student ID

        Returns:
            Active StudentEnrollment or None
        """
        return StudentEnrollment.objects.filter(
            student_id=student_id,
            enrollment_status=StudentEnrollment.EnrollmentStatus.ENROLLED
        ).select_related(
            "curriculum",
            "curriculum__program",
        ).first()

    @staticmethod
    def get_current_period_enrollment(student_id, academic_year: str, semester: int):
        """
        Get enrollment for current period.

        Args:
            student_id: The student ID
            academic_year: The academic year
            semester: The semester

        Returns:
            StudentEnrollment or None
        """
        return StudentEnrollment.objects.filter(
            student_id=student_id,
            academic_year=academic_year,
            semester=semester,
        ).select_related(
            "curriculum",
            "curriculum__program",
        ).first()

    @staticmethod
    def get_curriculum_enrollments(curriculum_id) -> QuerySet:
        """
        Get all students enrolled in a curriculum.

        Args:
            curriculum_id: The curriculum ID

        Returns:
            QuerySet of enrollments
        """
        return StudentEnrollment.objects.filter(
            curriculum_id=curriculum_id,
            enrollment_status=StudentEnrollment.EnrollmentStatus.ENROLLED
        ).select_related(
            "student",
            "curriculum",
        )

    @staticmethod
    def get_enrollments_by_status(
        student_id,
        status: str
    ) -> QuerySet:
        """
        Get enrollments filtered by status.

        Args:
            student_id: The student ID
            status: The enrollment status

        Returns:
            QuerySet of enrollments
        """
        return StudentEnrollment.objects.filter(
            student_id=student_id,
            enrollment_status=status
        ).select_related(
            "curriculum",
        ).order_by("-academic_year")

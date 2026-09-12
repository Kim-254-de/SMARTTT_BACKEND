"""
Django admin configuration for Students module.

Provides admin interface for managing students, academic progress,
and enrollments.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.db.models import Q

from apps.students.models import Student, AcademicProgress, StudentEnrollment


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    """Admin interface for Student model."""

    list_display = (
        'registration_number',
        'get_full_name',
        'email',
        'department_link',
        'program_link',
        'current_study_year',
        'academic_status',
        'is_active',
        'created_at',
    )

    list_filter = (
        'academic_status',
        'is_active',
        'enrollment_type',
        'department',
        'program',
        'admission_year',
        'created_at',
    )

    search_fields = (
        'registration_number',
        'first_name',
        'last_name',
        'email',
        'phone_number',
    )

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'academic_year_string',
        'is_graduated',
        'is_suspended',
    )

    fieldsets = (
        (_('User Link'), {
            'fields': ('user',),
        }),
        (_('Personal Information'), {
            'fields': (
                'registration_number',
                'first_name',
                'last_name',
                'gender',
                'email',
                'phone_number',
                'date_of_birth',
                'profile_photo',
            ),
        }),
        (_('Academic Organization'), {
            'fields': (
                'faculty',
                'department',
                'program',
            ),
        }),
        (_('Academic Progress'), {
            'fields': (
                'current_study_year',
                'current_semester',
                'admission_year',
                'academic_year_string',
            ),
        }),
        (_('Status'), {
            'fields': (
                'academic_status',
                'enrollment_type',
                'is_active',
            ),
        }),
        (_('Computed Fields'), {
            'fields': (
                'is_graduated',
                'is_suspended',
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': (
                'id',
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    ordering = ['-created_at']

    def get_full_name(self, obj):
        """Display student full name."""
        return obj.get_full_name()
    get_full_name.short_description = _('Full Name')

    def department_link(self, obj):
        """Link to department."""
        if obj.department:
            url = reverse('admin:departments_department_change', args=[obj.department.id])
            return f'<a href="{url}">{obj.department.name}</a>'
        return '-'
    department_link.allow_tags = True
    department_link.short_description = _('Department')

    def program_link(self, obj):
        """Link to program."""
        if obj.program:
            url = reverse('admin:programs_program_change', args=[obj.program.id])
            return f'<a href="{url}">{obj.program.name}</a>'
        return '-'
    program_link.allow_tags = True
    program_link.short_description = _('Program')

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        qs = super().get_queryset(request)
        return qs.select_related(
            'user',
            'department',
            'program',
            'faculty',
        )

    actions = [
        'make_active',
        'make_inactive',
        'suspend_students',
        'activate_students',
    ]

    def make_active(self, request, queryset):
        """Mark students as active."""
        updated = queryset.update(is_active=True)
        self.message_user(request, _(f'{updated} students marked as active.'))
    make_active.short_description = _('Mark selected students as active')

    def make_inactive(self, request, queryset):
        """Mark students as inactive."""
        updated = queryset.update(is_active=False)
        self.message_user(request, _(f'{updated} students marked as inactive.'))
    make_inactive.short_description = _('Mark selected students as inactive')

    def suspend_students(self, request, queryset):
        """Suspend selected students."""
        updated = queryset.update(academic_status=Student.AcademicStatus.SUSPENDED)
        self.message_user(request, _(f'{updated} students suspended.'))
    suspend_students.short_description = _('Suspend selected students')

    def activate_students(self, request, queryset):
        """Activate selected students."""
        updated = queryset.update(academic_status=Student.AcademicStatus.ACTIVE)
        self.message_user(request, _(f'{updated} students activated.'))
    activate_students.short_description = _('Activate selected students')


@admin.register(AcademicProgress)
class AcademicProgressAdmin(admin.ModelAdmin):
    """Admin interface for AcademicProgress model."""

    list_display = (
        'get_student',
        'academic_year',
        'study_year',
        'semester',
        'gpa',
        'cgpa',
        'total_credits',
        'academic_status',
        'created_at',
    )

    list_filter = (
        'academic_status',
        'academic_year',
        'semester',
        'created_at',
    )

    search_fields = (
        'student__registration_number',
        'student__first_name',
        'student__last_name',
    )

    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (_('Student'), {
            'fields': ('student',),
        }),
        (_('Academic Period'), {
            'fields': (
                'academic_year',
                'study_year',
                'semester',
            ),
        }),
        (_('Academic Metrics'), {
            'fields': (
                'gpa',
                'cgpa',
                'total_credits',
                'credits_this_semester',
            ),
        }),
        (_('Status'), {
            'fields': ('academic_status',),
        }),
        (_('Metadata'), {
            'fields': (
                'recorded_by',
                'id',
                'created_at',
                'updated_at',
            ),
        }),
    )

    ordering = ['-academic_year', '-semester']

    def get_student(self, obj):
        """Display student information."""
        return f'{obj.student.registration_number} - {obj.student.get_full_name()}'
    get_student.short_description = _('Student')

    def get_queryset(self, request):
        """Optimize queryset."""
        qs = super().get_queryset(request)
        return qs.select_related('student', 'recorded_by')


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    """Admin interface for StudentEnrollment model."""

    list_display = (
        'get_student',
        'academic_year',
        'study_year',
        'semester',
        'curriculum_link',
        'enrollment_status',
        'enrollment_date',
    )

    list_filter = (
        'enrollment_status',
        'academic_year',
        'semester',
        'enrollment_date',
    )

    search_fields = (
        'student__registration_number',
        'student__first_name',
        'student__last_name',
        'curriculum__program__code',
    )

    readonly_fields = (
        'id',
        'enrollment_date',
        'created_at',
        'updated_at',
    )

    fieldsets = (
        (_('Student'), {
            'fields': ('student',),
        }),
        (_('Curriculum'), {
            'fields': ('curriculum',),
        }),
        (_('Academic Period'), {
            'fields': (
                'academic_year',
                'study_year',
                'semester',
            ),
        }),
        (_('Enrollment'), {
            'fields': (
                'enrollment_status',
                'enrollment_date',
            ),
        }),
        (_('Notes'), {
            'fields': ('notes',),
        }),
        (_('Metadata'), {
            'fields': (
                'id',
                'created_at',
                'updated_at',
            ),
        }),
    )

    ordering = ['-academic_year', '-semester']

    def get_student(self, obj):
        """Display student information."""
        return f'{obj.student.registration_number} - {obj.student.get_full_name()}'
    get_student.short_description = _('Student')

    def curriculum_link(self, obj):
        """Link to curriculum."""
        if obj.curriculum:
            url = reverse('admin:curriculum_curriculum_change', args=[obj.curriculum.id])
            return f'<a href="{url}">{obj.curriculum.program.code}</a>'
        return '-'
    curriculum_link.allow_tags = True
    curriculum_link.short_description = _('Curriculum')

    def get_queryset(self, request):
        """Optimize queryset."""
        qs = super().get_queryset(request)
        return qs.select_related('student', 'curriculum', 'curriculum__program')

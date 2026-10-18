from django.urls import path

from .timetabling_views import (
    AllocatorAuthenticateView,
    AllocatorDepartmentsView,
    AllocatorIdentityView,
    AllocatorLecturerSessionsView,
    AllocatorLecturersView,
    AllocatorSectionDetailView,
    AllocatorSectionLecturerView,
    AllocatorSectionsView,
    AllocatorTermsView,
    GeneratorAuthenticateView,
    GeneratorIdentityView,
    GeneratorPublicationView,
    GeneratorPublishView,
    GeneratorSnapshotView,
    GeneratorTermsView,
)
from .views import (
    AttendanceAuthenticateView,
    AttendanceLecturerUnitsView,
    AttendanceStaffLookupView,
    AttendanceStudentLookupView,
    AttendanceStudentUnitsView,
)

urlpatterns = [
    path(
        "attendance/authenticate/",
        AttendanceAuthenticateView.as_view(),
        name="integrations-attendance-authenticate",
    ),
    path(
        "attendance/lecturer-units/",
        AttendanceLecturerUnitsView.as_view(),
        name="integrations-attendance-lecturer-units",
    ),
    path(
        "attendance/students/",
        AttendanceStudentLookupView.as_view(),
        name="integrations-attendance-student",
    ),
    path(
        "attendance/staff/",
        AttendanceStaffLookupView.as_view(),
        name="integrations-attendance-staff",
    ),
    path(
        "attendance/student-units/",
        AttendanceStudentUnitsView.as_view(),
        name="integrations-attendance-student-units",
    ),
    # Timetable Allocator (ALLOCATOR_API_KEY)
    path("allocator/authenticate/", AllocatorAuthenticateView.as_view(), name="integrations-allocator-authenticate"),
    path("allocator/identity/", AllocatorIdentityView.as_view(), name="integrations-allocator-identity"),
    path("allocator/terms/", AllocatorTermsView.as_view(), name="integrations-allocator-terms"),
    path("allocator/departments/", AllocatorDepartmentsView.as_view(), name="integrations-allocator-departments"),
    path("allocator/sections/", AllocatorSectionsView.as_view(), name="integrations-allocator-sections"),
    path(
        "allocator/sections/<str:key>/",
        AllocatorSectionDetailView.as_view(),
        name="integrations-allocator-section",
    ),
    path(
        "allocator/sections/<str:key>/lecturer/",
        AllocatorSectionLecturerView.as_view(),
        name="integrations-allocator-section-lecturer",
    ),
    path("allocator/lecturers/", AllocatorLecturersView.as_view(), name="integrations-allocator-lecturers"),
    path(
        "allocator/lecturers/<uuid:lecturer_id>/sessions/",
        AllocatorLecturerSessionsView.as_view(),
        name="integrations-allocator-lecturer-sessions",
    ),
    # Timetable Generator (GENERATOR_API_KEY)
    path("generator/authenticate/", GeneratorAuthenticateView.as_view(), name="integrations-generator-authenticate"),
    path("generator/identity/", GeneratorIdentityView.as_view(), name="integrations-generator-identity"),
    path("generator/terms/", GeneratorTermsView.as_view(), name="integrations-generator-terms"),
    path("generator/snapshot/", GeneratorSnapshotView.as_view(), name="integrations-generator-snapshot"),
    path("generator/publish/", GeneratorPublishView.as_view(), name="integrations-generator-publish"),
    path(
        "generator/publish/<int:version>/",
        GeneratorPublicationView.as_view(),
        name="integrations-generator-publication",
    ),
]

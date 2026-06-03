from .serializers import (
    StudentListSerializer,
    StudentDetailSerializer,
    StudentCreateUpdateSerializer,
    StudentProfileUpdateSerializer,
    StudentMyProfileSerializer,
    AcademicProgressSerializer,
    StudentEnrollmentSerializer,
)
from .student_serializer import StudentSerializer

__all__ = [
    "StudentListSerializer",
    "StudentDetailSerializer",
    "StudentCreateUpdateSerializer",
    "StudentProfileUpdateSerializer",
    "StudentMyProfileSerializer",
    "AcademicProgressSerializer",
    "StudentEnrollmentSerializer",
    "StudentSerializer",
]

# Alias for backwards compatibility
StudentSerializer = StudentDetailSerializer

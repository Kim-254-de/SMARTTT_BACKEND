from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from .models import Department, Faculty, Lecturer, Program, Room
from .serializers import (
    DepartmentSerializer, FacultySerializer, LecturerSerializer,
    ProgramSerializer, RoomSerializer,
)


class FacultyViewSet(ModelViewSet):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        return [IsAdminUser()]


class DepartmentViewSet(ModelViewSet):
    queryset = Department.objects.select_related("faculty").all()
    serializer_class = DepartmentSerializer
    filterset_fields = ["faculty"]
    search_fields = ["name", "code"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        return [IsAdminUser()]


class ProgramViewSet(ModelViewSet):
    queryset = Program.objects.select_related("department", "department__faculty").all()
    serializer_class = ProgramSerializer
    filterset_fields = ["department"]
    search_fields = ["name", "code"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        return [IsAdminUser()]


class RoomViewSet(ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    search_fields = ["code", "name", "building"]
    filterset_fields = ["room_type"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        return [IsAdminUser()]


class LecturerViewSet(ReadOnlyModelViewSet):
    queryset = Lecturer.objects.select_related("user", "department").all()
    serializer_class = LecturerSerializer
    filterset_fields = ["department"]
    search_fields = ["user__first_name", "user__last_name"]
    permission_classes = [IsAuthenticated]

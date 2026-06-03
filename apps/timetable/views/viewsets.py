from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from apps.timetable.models import Room, TimeSlot, TimetableSession
from apps.timetable.serializers import (
    RoomListSerializer,
    RoomDetailSerializer,
    RoomCreateUpdateSerializer,
    TimeSlotListSerializer,
    TimeSlotDetailSerializer,
    TimeSlotCreateUpdateSerializer,
    TimetableSessionListSerializer,
    TimetableSessionDetailSerializer,
    TimetableSessionCreateUpdateSerializer,
    StudentTimetableSessionSerializer,
)
from apps.timetable.permissions import (
    CanManageRooms,
    CanManageTimeSlots,
    CanManageTimetable,
    CanViewTimetable,
    IsStudentOrAdmin,
)
from apps.timetable.selectors import TimetableSessionSelector, RoomSelector, TimeSlotSelector
from apps.timetable.services import (
    TimetableSessionService,
    TimetableFilterService,
    RoomAllocationService,
    LecturerScheduleService,
    TimetableConflictService,
)


class RoomViewSet(viewsets.ModelViewSet):
    """
    ViewSet for room management.

    Endpoints:
    - GET /api/v1/timetable/rooms/ - List rooms
    - POST /api/v1/timetable/rooms/ - Create room
    - GET /api/v1/timetable/rooms/{id}/ - Get room
    - PUT/PATCH /api/v1/timetable/rooms/{id}/ - Update room
    - DELETE /api/v1/timetable/rooms/{id}/ - Delete room
    """

    permission_classes = [CanManageRooms]
    filterset_fields = ["building", "room_type", "status", "capacity"]
    search_fields = ["code", "name", "building"]
    ordering_fields = ["code", "building", "capacity"]
    ordering = ["building", "code"]

    def get_queryset(self):
        return RoomSelector.get_all_available_rooms()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return RoomDetailSerializer
        elif self.action in ["create", "update", "partial_update"]:
            return RoomCreateUpdateSerializer
        return RoomListSerializer

    @action(detail=False, methods=["get"])
    def available_rooms(self, request):
        """Get rooms available for specific time slot."""
        capacity = request.query_params.get("capacity")
        day = request.query_params.get("day_of_week")
        time_slot_id = request.query_params.get("time_slot_id")
        academic_year = request.query_params.get("academic_year")
        semester = request.query_params.get("semester")

        if not all([capacity, day, time_slot_id, academic_year, semester]):
            raise ValidationError(
                {"detail": "capacity, day_of_week, time_slot_id, academic_year, semester are required"}
            )

        available = RoomAllocationService.get_available_rooms(
            int(capacity), day, time_slot_id, academic_year, int(semester)
        )

        serializer = RoomDetailSerializer(available, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def schedule(self, request, pk=None):
        """Get room schedule."""
        room = self.get_object()
        day = request.query_params.get("day_of_week")
        academic_year = request.query_params.get("academic_year")

        schedule = RoomAllocationService.get_room_schedule(str(room.id), day, academic_year)
        serializer = TimetableSessionListSerializer(schedule, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def occupancy(self, request, pk=None):
        """Get room occupancy report."""
        room = self.get_object()
        academic_year = request.query_params.get("academic_year")

        report = RoomAllocationService.get_room_occupancy_report(str(room.id), academic_year)
        return Response(report)


class TimeSlotViewSet(viewsets.ModelViewSet):
    """
    ViewSet for time slot management.

    Endpoints:
    - GET /api/v1/timetable/timeslots/ - List time slots
    - POST /api/v1/timetable/timeslots/ - Create time slot
    - GET /api/v1/timetable/timeslots/{id}/ - Get time slot
    - PUT/PATCH /api/v1/timetable/timeslots/{id}/ - Update time slot
    - DELETE /api/v1/timetable/timeslots/{id}/ - Delete time slot
    """

    permission_classes = [CanManageTimeSlots]
    filterset_fields = ["status"]
    ordering_fields = ["start_time", "duration_minutes"]
    ordering = ["start_time"]

    def get_queryset(self):
        return TimeSlotSelector.get_all_active_slots()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TimeSlotDetailSerializer
        elif self.action in ["create", "update", "partial_update"]:
            return TimeSlotCreateUpdateSerializer
        return TimeSlotListSerializer


class TimetableSessionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for timetable session management.

    Endpoints:
    - GET /api/v1/timetable/sessions/ - List sessions
    - POST /api/v1/timetable/sessions/ - Create session
    - GET /api/v1/timetable/sessions/{id}/ - Get session
    - PUT/PATCH /api/v1/timetable/sessions/{id}/ - Update session
    - DELETE /api/v1/timetable/sessions/{id}/ - Delete session
    - GET /api/v1/timetable/sessions/my-timetable/ - Student personalized timetable
    - GET /api/v1/timetable/sessions/lecturer-schedule/ - Lecturer teaching schedule
    - GET /api/v1/timetable/sessions/conflicts/ - Timetable conflicts
    """

    permission_classes = [CanManageTimetable]
    filterset_fields = ["academic_year", "semester", "study_year", "day_of_week", "status", "program", "department"]
    search_fields = ["unit__code", "unit__title", "room__code", "lecturer__user__last_name"]
    ordering_fields = ["day_of_week", "academic_year", "semester"]
    ordering = ["day_of_week", "time_slot__start_time"]

    def get_queryset(self):
        return TimetableSessionSelector.get_all_sessions()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TimetableSessionDetailSerializer
        elif self.action in ["create", "update", "partial_update"]:
            return TimetableSessionCreateUpdateSerializer
        elif self.action == "my_timetable":
            return StudentTimetableSessionSerializer
        return TimetableSessionListSerializer

    def perform_create(self, serializer):
        """Create with current user as creator."""
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="my-timetable", permission_classes=[CanViewTimetable])
    def my_timetable(self, request):
        """
        Get personalized timetable for logged-in student.

        Filters based on: Program → Curriculum → Units
        """
        # Check if user is student
        from apps.students.models import Student

        try:
            student = Student.objects.get(user=request.user)
        except Student.DoesNotExist:
            return Response(
                {"detail": "User does not have a student profile"},
                status=status.HTTP_404_NOT_FOUND,
            )

        academic_year = request.query_params.get("academic_year")
        semester = request.query_params.get("semester")

        if not academic_year or not semester:
            return Response(
                {"detail": "academic_year and semester query parameters are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sessions = TimetableFilterService.get_student_timetable(
            student, academic_year, int(semester)
        )

        # Optional day filter
        day = request.query_params.get("day_of_week")
        if day:
            sessions = TimetableFilterService.get_filtered_timetable_by_day(sessions, day)

        serializer = StudentTimetableSessionSerializer(sessions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="lecturer-schedule", permission_classes=[CanViewTimetable])
    def lecturer_schedule(self, request):
        """Get teaching schedule for logged-in lecturer."""
        from apps.lecturers.models import Lecturer

        try:
            lecturer = Lecturer.objects.get(user=request.user)
        except Lecturer.DoesNotExist:
            return Response(
                {"detail": "User does not have a lecturer profile"},
                status=status.HTTP_404_NOT_FOUND,
            )

        academic_year = request.query_params.get("academic_year")
        semester = request.query_params.get("semester")

        schedule = LecturerScheduleService.get_lecturer_schedule(
            str(lecturer.id), academic_year, semester
        )

        workload = LecturerScheduleService.get_lecturer_workload(
            str(lecturer.id), academic_year or "2024/2025", int(semester or 1)
        )

        serializer = TimetableSessionListSerializer(schedule, many=True)
        return Response({"schedule": serializer.data, "workload": workload})

    @action(detail=False, methods=["get"], permission_classes=[CanManageTimetable])
    def conflicts(self, request):
        """
        Get timetable conflict report.

        Accessible by: Super admin, Registrar, Department admin
        """
        academic_year = request.query_params.get("academic_year")
        semester = request.query_params.get("semester")
        department_id = request.query_params.get("department_id")

        if not academic_year or not semester:
            return Response(
                {"detail": "academic_year and semester query parameters are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report = TimetableConflictService.get_conflict_report(
            academic_year, int(semester), department_id
        )

        return Response(report)

    @action(detail=False, methods=["post"])
    def check_availability(self, request):
        """Check if a time slot is available."""
        room_id = request.data.get("room_id")
        lecturer_id = request.data.get("lecturer_id")
        day = request.data.get("day_of_week")
        time_slot_id = request.data.get("time_slot_id")
        academic_year = request.data.get("academic_year")
        semester = request.data.get("semester")

        if not all([day, time_slot_id, academic_year, semester]):
            raise ValidationError(
                {"detail": "day_of_week, time_slot_id, academic_year, semester are required"}
            )

        conflicts = TimetableConflictService.detect_conflicts(
            day, time_slot_id, room_id, lecturer_id, academic_year, int(semester)
        )

        is_available = len(conflicts) == 0

        return Response({"available": is_available, "conflicts": conflicts})

    @action(detail=True, methods=["post"])
    def enroll_student(self, request, pk=None):
        """Enroll a student in session."""
        session = self.get_object()

        try:
            updated_session = TimetableSessionService.enroll_student_in_session(str(session.id))
            serializer = TimetableSessionDetailSerializer(updated_session)
            return Response(serializer.data)
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def withdraw_student(self, request, pk=None):
        """Withdraw a student from session."""
        session = self.get_object()
        updated_session = TimetableSessionService.withdraw_student_from_session(str(session.id))
        serializer = TimetableSessionDetailSerializer(updated_session)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a session."""
        session = self.get_object()
        reason = request.data.get("reason", "")

        cancelled_session = TimetableSessionService.cancel_session(str(session.id), reason)
        serializer = TimetableSessionDetailSerializer(cancelled_session)
        return Response(serializer.data)

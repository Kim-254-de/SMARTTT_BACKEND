from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StudentUnit
from .scraper import ScraperError, scrape_student_units
from .serializers import (
    ManualSyncSerializer,
    PortalSyncSerializer,
    SetUnitGroupSerializer,
    StudentUnitSerializer,
)
from .services import sync_units_for_student


class PortalSyncView(APIView):
    """
    POST /api/v1/courses/sync/portal/
    Student provides portal username + password ONCE.
    We scrape their registered units, save to StudentUnit, discard credentials.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = PortalSyncSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            unit_list = scrape_student_units(
                s.validated_data["portal_username"],
                s.validated_data["portal_password"],
            )
        except ScraperError as exc:
            if exc.code == "invalid_credentials":
                detail = "The portal admission number or password is incorrect."
            elif exc.code == "portal_unavailable":
                detail = "The student portal is currently unavailable. Please try again later."
            else:
                detail = "We could not read your portal details. Please try again."
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        if not unit_list:
            return Response(
                {"detail": "No registered units are available for this semester. "
                           "Please confirm your units are registered on the portal."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = sync_units_for_student(request.user, unit_list)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class ManualSyncView(APIView):
    """
    POST /api/v1/courses/sync/manual/
    Student manually provides unit codes if portal scraping is unavailable.
    Body: {"unit_codes": ["COSC 328", "COSC 371"]}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = ManualSyncSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        unit_list = [{"unit_code": code} for code in s.validated_data["unit_codes"]]

        try:
            result = sync_units_for_student(request.user, unit_list)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class MyCoursesView(ListAPIView):
    """
    GET /api/v1/courses/my-courses/
    Returns the current student's registered units for the current term.
    """
    serializer_class = StudentUnitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            StudentUnit.objects.select_related("unit", "unit__department", "term")
            .filter(user=self.request.user)
            .order_by("unit__code")
        )


class SetUnitGroupView(APIView):
    """
    PATCH /api/v1/courses/my-courses/{id}/group/
    Body: {"class_group": "GR B"}

    Records which elective/practical group the student is actually in for
    one specific registered unit. Only meaningful when that unit is split
    into more than one group for the student's program+stream (see
    StudentUnitSerializer.available_groups / available_groups_for_unit) -
    different unit pools within the same stream use unrelated group
    lettering at once, so this can't be set once for the whole stream the
    way `timetable_group` (the numbered sub-stream) is.

    Pass "" to clear a previous choice back to "show every group".
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk=None):
        from apps.schedule.services import available_groups_for_unit

        try:
            student_unit = StudentUnit.objects.select_related("unit").get(
                pk=pk, user=request.user
            )
        except StudentUnit.DoesNotExist:
            return Response({"detail": "Registered unit not found."}, status=status.HTTP_404_NOT_FOUND)

        s = SetUnitGroupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        chosen = s.validated_data["class_group"].strip()

        if chosen:
            options = available_groups_for_unit(request.user, student_unit.term, student_unit.unit_id)
            matched = next((o for o in options if o.upper() == chosen.upper()), None)
            if not matched:
                return Response(
                    {
                        "detail": f"'{chosen}' is not a valid group for {student_unit.unit.code}.",
                        "available_groups": options,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            chosen = matched

        student_unit.class_group = chosen
        student_unit.save(update_fields=["class_group"])

        return Response(StudentUnitSerializer(student_unit, context={"request": request}).data)

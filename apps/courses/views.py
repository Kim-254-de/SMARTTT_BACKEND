from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StudentUnit
from .scraper import ScraperError, scrape_student_units
from .serializers import ManualSyncSerializer, PortalSyncSerializer, StudentUnitSerializer
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
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not unit_list:
            return Response(
                {"detail": "No registered units found on the portal. "
                           "Make sure you have registered units for this semester."},
                status=status.HTTP_200_OK,
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

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import generate_for_user


class MyScheduleView(APIView):
    """
    GET /api/v1/schedule/me/
    Returns the personalised timetable for the authenticated student.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = generate_for_user(request.user)
        return Response(payload)

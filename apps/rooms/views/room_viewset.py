from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.rooms.models import Room
from apps.rooms.serializers import RoomSerializer
from apps.rooms.services.room_import import RoomImportError, capacity_summary, import_rooms

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class RoomViewSet(ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["building", "room_type"]
    search_fields = ["code", "building"]

    @action(detail=False, methods=["post"], url_path="upload", permission_classes=[IsAdminUser], parser_classes=[MultiPartParser])
    def upload(self, request):
        """
        POST /api/v1/rooms/rooms/upload/  (multipart, field "file")
        Creates or updates rooms from a CSV/XLSX of venue capacities.
        """
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=400)
        if file.size > MAX_UPLOAD_BYTES:
            return Response({"detail": "The file is too large (max 5 MB)."}, status=400)

        try:
            result = import_rooms(file.name, file.read())
        except RoomImportError as exc:
            return Response({"detail": str(exc)}, status=400)

        saved = result["created"] + result["updated"] + result["unchanged"]
        result["detail"] = (
            f"{saved} room(s) processed: {result['created']} added, {result['updated']} updated"
            + (f", {len(result['errors'])} row issue(s)." if result["errors"] else ".")
        )
        result["summary"] = capacity_summary()
        return Response(result, status=200)

    @action(detail=False, methods=["get"], url_path="capacity-summary", permission_classes=[IsAdminUser])
    def capacity_summary(self, request):
        """GET /api/v1/rooms/rooms/capacity-summary/ — rooms still missing a real capacity."""
        return Response(capacity_summary())

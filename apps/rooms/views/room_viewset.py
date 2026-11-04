from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.rooms.models import Room
from apps.rooms.serializers import RoomSerializer
from apps.rooms.services.room_import import RoomImportError, capacity_summary, import_rooms
from apps.rooms.services.room_merge import duplicate_groups, merge_all, merge_rooms

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

    @action(detail=False, methods=["get"], url_path="everything", permission_classes=[IsAdminUser])
    def everything(self, request):
        """Every venue, unpaged, for the admin's table (the placeholder TBA room left out)."""
        rooms = Room.objects.exclude(code="TBA").order_by("building", "code")
        return Response({"rooms": RoomSerializer(rooms, many=True).data})

    @action(detail=False, methods=["get"], url_path="duplicates", permission_classes=[IsAdminUser])
    def duplicates(self, request):
        """Rooms known by more than one code ("TC1", "TC 1"), and what merging would do. Changes nothing."""
        return Response({"groups": duplicate_groups()})

    @action(detail=False, methods=["post"], url_path="merge-duplicates", permission_classes=[IsAdminUser])
    def merge_duplicates(self, request):
        """Folds every such group into one room; slots and exam seats move with it."""
        result = merge_all()
        self._after_merge()
        return Response(result)

    @action(detail=False, methods=["post"], url_path="merge", permission_classes=[IsAdminUser])
    def merge(self, request):
        """{keep, merge: [ids]}: rooms the admin knows are one, whatever their codes ("Conference Hall", "ED 4")."""
        keep = Room.objects.filter(pk=request.data.get("keep")).first()
        ids = request.data.get("merge") or []
        others = list(Room.objects.filter(pk__in=ids).exclude(code="TBA"))
        if keep is None or keep.code == "TBA" or not others or len(others) != len(ids) or keep in others:
            return Response({"detail": "Choose the venue to keep and at least one other venue to merge into it."}, status=400)
        result = merge_rooms(keep, others)
        self._after_merge()
        return Response(result)

    @staticmethod
    def _after_merge():
        from apps.common.services.cache_service import PersonalizationCacheService

        PersonalizationCacheService.clear_all()

    @action(detail=False, methods=["get"], url_path="capacity-summary", permission_classes=[IsAdminUser])
    def capacity_summary(self, request):
        """GET /api/v1/rooms/rooms/capacity-summary/ — rooms still missing a real capacity."""
        return Response(capacity_summary())

from rest_framework.viewsets import ModelViewSet

from apps.common.permissions import IsAdminOrReadOnly
from apps.rooms.models import Room
from apps.rooms.serializers import RoomSerializer


class RoomViewSet(ModelViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ["building", "room_type"]
    search_fields = ["code", "building"]

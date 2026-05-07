from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer


class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email", "university_id"]
    ordering_fields = ["created_at", "updated_at", "username"]

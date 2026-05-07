from rest_framework.permissions import BasePermission


class IsRegistrarOrAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_staff or request.user.role in {"registrar", "admin"}

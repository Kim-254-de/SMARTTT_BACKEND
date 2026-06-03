from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import UserViewSet
from apps.accounts.views.auth_views import LoginView, RegisterView, ProfileView, PasswordResetView

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/login/", LoginView.as_view(), name="auth_login"),
    path("auth/register/", RegisterView.as_view(), name="auth_register"),
    path("auth/profile/", ProfileView.as_view(), name="auth_profile"),
    path("auth/profile/update/", ProfileView.as_view(), name="auth_profile_update"),
    path("auth/password/reset/", PasswordResetView.as_view(), name="auth_password_reset"),
]

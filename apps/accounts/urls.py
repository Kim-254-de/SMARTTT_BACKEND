from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views.auth_views import (
    GoogleAuthView,
    LecturerProfileView,
    LecturerRegisterView,
    LecturerStudentsView,
    LoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    RegisterView,
    StaffIDListView,
    StaffIDUploadView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("google/", GoogleAuthView.as_view(), name="google-auth"),
    path("lecturer/register/", LecturerRegisterView.as_view(), name="lecturer-register"),
    path("lecturer/profile/", LecturerProfileView.as_view(), name="lecturer-profile"),
    path("lecturer/students/", LecturerStudentsView.as_view(), name="lecturer-students"),
    path("staff-ids/upload/", StaffIDUploadView.as_view(), name="staff-id-upload"),
    path("staff-ids/", StaffIDListView.as_view(), name="staff-id-list"),
]

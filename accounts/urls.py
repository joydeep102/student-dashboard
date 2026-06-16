from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path

from . import google_login, views

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            redirect_authenticated_user=True,
            extra_context={"google_enabled": settings.GOOGLE_LOGIN_ENABLED},
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url="/accounts/profile/",
        ),
        name="password_change",
    ),
    # Sign in with Google
    path("google/login/", google_login.google_login, name="google_login"),
    path("google/callback/", google_login.google_callback, name="google_callback"),
]

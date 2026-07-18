from django.contrib.auth import views as auth_views
from django.urls import path

from . import google_login, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/forgot/", views.forgot_password, name="forgot_password"),
    path("profile/", views.profile, name="profile"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),
    # Sign in with Google
    path("google/login/", google_login.google_login, name="google_login"),
    path("google/callback/", google_login.google_callback, name="google_callback"),
    # Admin-only: connect server-side Calendar/YouTube (?kind=calendar|youtube)
    path("google/connect/", google_login.google_connect, name="google_connect"),
    # Admin-only: enter Client ID/Secret + see the redirect URI
    path("google/settings/", views.google_settings, name="google_settings"),
]

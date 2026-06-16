"""Sign in with Google for portal users.

Server-side OAuth2 (authorization code) flow. On callback we read the verified
Google email and log in the matching **existing, active** user. Accounts are
admin-created, so an unknown email is rejected (no auto-signup).
"""

import logging
import os
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect

User = get_user_model()
log = logging.getLogger(__name__)

# Google returns the granted scopes in a different form/order than requested
# (e.g. it adds "openid"), which makes oauthlib raise during token exchange.
# Relaxing the check lets the standard "openid email profile" login succeed.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _login_error(msg):
    return redirect("/accounts/login/?" + urlencode({"auth_error": msg}))


def _allow_insecure_transport():
    # oauthlib refuses plain http; permit it for local DEBUG over http only.
    if settings.DEBUG and settings.GOOGLE_LOGIN_REDIRECT_URI.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _flow(state=None):
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_LOGIN_CLIENT_ID,
            "client_secret": settings.GOOGLE_LOGIN_CLIENT_SECRET,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_LOGIN_REDIRECT_URI],
        }
    }
    kwargs = {"scopes": SCOPES, "redirect_uri": settings.GOOGLE_LOGIN_REDIRECT_URI}
    if state:
        kwargs["state"] = state
    return Flow.from_client_config(client_config, **kwargs)


def google_login(request):
    """Kick off the Google OAuth flow."""
    if not settings.GOOGLE_LOGIN_ENABLED:
        return _login_error("Google login isn't configured.")
    _allow_insecure_transport()
    flow = _flow()
    auth_url, state = flow.authorization_url(
        prompt="select_account", access_type="online", include_granted_scopes="true"
    )
    request.session["g_oauth_state"] = state
    return redirect(auth_url)


def google_callback(request):
    """Handle Google's redirect: verify email and log the user in."""
    if not settings.GOOGLE_LOGIN_ENABLED:
        return _login_error("Google login isn't configured.")
    if request.GET.get("error"):
        return _login_error("Google sign-in was cancelled.")

    _allow_insecure_transport()
    state = request.session.pop("g_oauth_state", None)
    # Build the authorization response from the CONFIGURED redirect URI (https)
    # rather than request.build_absolute_uri(), so it works correctly behind an
    # HTTPS reverse proxy that forwards plain http to the app.
    query = request.META.get("QUERY_STRING", "")
    auth_response = settings.GOOGLE_LOGIN_REDIRECT_URI
    if query:
        auth_response = f"{auth_response}?{query}"
    try:
        flow = _flow(state=state)
        flow.fetch_token(authorization_response=auth_response)
    except Exception:
        log.exception("Google OAuth token exchange failed")
        return _login_error("Google sign-in failed. Please try again.")

    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        info = id_token.verify_oauth2_token(
            flow.credentials.id_token, g_requests.Request(),
            settings.GOOGLE_LOGIN_CLIENT_ID, clock_skew_in_seconds=10,
        )
    except Exception:
        log.exception("Google ID token verification failed")
        return _login_error("Could not verify your Google account.")

    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", False):
        return _login_error("Your Google email isn't verified.")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return _login_error(
            "No account found for this Google email. Please ask your admin to create one."
        )

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("courses:dashboard")

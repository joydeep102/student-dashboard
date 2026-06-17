"""Sign in with Google for portal users.

Server-side OAuth2 (authorization code) flow. On callback we read the verified
Google email and log in the matching **existing, active** user. Accounts are
admin-created, so an unknown email is rejected (no auto-signup).
"""

import logging
import os
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from . import google_config

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

# "Connect" flows that reuse this same web client to authorize the server-side
# Google APIs and cache their tokens. Maps kind -> (scopes, settings attr for
# the token-file path or None for per-trainer, human label, redirect target).
CONNECT = {
    "calendar": (
        ["https://www.googleapis.com/auth/calendar.events"],
        "GOOGLE_OAUTH_TOKEN_FILE",
        "Google Calendar / Meet",
        "admin:index",
    ),
    "youtube": (
        ["https://www.googleapis.com/auth/youtube.upload"],
        "GOOGLE_YOUTUBE_TOKEN_FILE",
        "YouTube upload",
        "admin:index",
    ),
    "gmail": (
        ["https://www.googleapis.com/auth/gmail.send"],
        "GOOGLE_GMAIL_TOKEN_FILE",
        "Gmail (send mail)",
        "admin:index",
    ),
    # Per-trainer: token saved to GOOGLE_TRAINER_TOKEN_DIR/<user_id>.json so the
    # trainer becomes the host of their batch's Meet links.
    "trainer": (
        ["https://www.googleapis.com/auth/calendar.events"],
        None,
        "Google (host your live classes)",
        "trainers:live",
    ),
}


def trainer_token_path(user):
    """Path to a trainer's cached OAuth token (keyed by user id)."""
    return os.path.join(settings.GOOGLE_TRAINER_TOKEN_DIR, f"{user.id}.json")


def _login_error(msg):
    return redirect("/accounts/login/?" + urlencode({"auth_error": msg}))


def _allow_insecure_transport():
    # oauthlib refuses plain http; permit it for local DEBUG over http only.
    if settings.DEBUG and google_config.load()["redirect_uri"].startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _flow(scopes=None, state=None):
    from google_auth_oauthlib.flow import Flow

    cfg = google_config.load()
    client_config = {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [cfg["redirect_uri"]],
        }
    }
    kwargs = {"scopes": scopes or SCOPES, "redirect_uri": cfg["redirect_uri"]}
    if state:
        kwargs["state"] = state
    return Flow.from_client_config(client_config, **kwargs)


def google_login(request):
    """Kick off the Google OAuth flow."""
    if not google_config.load()["enabled"]:
        return _login_error("Google login isn't configured.")
    _allow_insecure_transport()
    request.session.pop("g_connect_kind", None)  # this is a login, not a connect
    flow = _flow()
    auth_url, state = flow.authorization_url(
        prompt="select_account", access_type="online", include_granted_scopes="true"
    )
    request.session["g_oauth_state"] = state
    # Persist the PKCE verifier so the callback (a fresh Flow) can complete the
    # token exchange — otherwise Google rejects it with "Missing code verifier".
    request.session["g_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


def google_connect(request):
    """Admin-only: authorize the server-side Calendar/YouTube APIs.

    Reuses the Sign-in-with-Google web client and its registered redirect URI,
    requesting offline access so we cache a refresh token. ``?kind=`` selects
    which integration (calendar | youtube).
    """
    kind = request.GET.get("kind", "")
    if kind not in CONNECT:
        return _login_error("Unknown Google connection type.")
    if not request.user.is_authenticated:
        raise PermissionDenied
    if kind == "trainer":
        role = getattr(request.user, "role", None)
        if not (role in ("instructor", "admin") or request.user.is_superuser):
            raise PermissionDenied("Trainer access only.")
    elif not request.user.is_staff:
        raise PermissionDenied("Admin access only.")
    if not google_config.load()["enabled"]:
        return _login_error("Google client isn't configured. Set it in Admin → Google API settings.")

    _allow_insecure_transport()
    scopes = CONNECT[kind][0]
    flow = _flow(scopes=scopes)
    # offline + consent so Google returns a refresh token we can store and reuse.
    auth_url, state = flow.authorization_url(
        prompt="consent", access_type="offline", include_granted_scopes="false"
    )
    request.session["g_oauth_state"] = state
    request.session["g_connect_kind"] = kind
    request.session["g_code_verifier"] = flow.code_verifier  # PKCE
    return redirect(auth_url)


def _finish_connect(request, kind, state, code_verifier, auth_response):
    """Exchange the code for tokens and cache them for the chosen integration."""
    scopes, token_attr, label, redirect_to = CONNECT[kind]
    token_file = (
        trainer_token_path(request.user) if token_attr is None
        else getattr(settings, token_attr)
    )
    try:
        flow = _flow(scopes=scopes, state=state)
        flow.code_verifier = code_verifier  # restore PKCE verifier
        flow.fetch_token(authorization_response=auth_response)
    except Exception:
        log.exception("Google %s connect: token exchange failed", kind)
        messages.error(request, f"Couldn't connect {label}. Please try again.")
        return redirect(redirect_to)

    creds = flow.credentials
    if not creds.refresh_token:
        # Without a refresh token the link would die in an hour. Force re-consent.
        messages.error(
            request,
            f"{label}: Google didn't return a refresh token. Remove the app's "
            "access at myaccount.google.com/permissions, then connect again.",
        )
        return redirect(redirect_to)
    try:
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    except Exception:
        log.exception("Could not save %s token to %s", kind, token_file)
        messages.error(request, f"{label}: authorized but couldn't save the token file.")
        return redirect(redirect_to)

    log.info("%s connected; token saved to %s", label, token_file)
    messages.success(request, f"{label} connected ✓")
    return redirect(redirect_to)


def google_callback(request):
    """Handle Google's redirect: log a user in, or finish an admin connect."""
    cfg = google_config.load()
    if not cfg["enabled"]:
        return _login_error("Google login isn't configured.")
    connect_kind = request.session.pop("g_connect_kind", None)
    if request.GET.get("error"):
        request.session.pop("g_code_verifier", None)
        if connect_kind:
            messages.error(request, "Google authorization was cancelled.")
            return redirect("admin:index")
        return _login_error("Google sign-in was cancelled.")

    _allow_insecure_transport()
    state = request.session.pop("g_oauth_state", None)
    code_verifier = request.session.pop("g_code_verifier", None)
    # Build the authorization response from the CONFIGURED redirect URI (https)
    # rather than request.build_absolute_uri(), so it works correctly behind an
    # HTTPS reverse proxy that forwards plain http to the app.
    query = request.META.get("QUERY_STRING", "")
    auth_response = cfg["redirect_uri"]
    if query:
        auth_response = f"{auth_response}?{query}"

    # Admin Calendar/YouTube connection rather than a user login.
    if connect_kind in CONNECT:
        return _finish_connect(request, connect_kind, state, code_verifier, auth_response)

    try:
        flow = _flow(state=state)
        flow.code_verifier = code_verifier  # restore PKCE verifier
        flow.fetch_token(authorization_response=auth_response)
    except Exception:
        log.exception("Google OAuth token exchange failed")
        return _login_error("Google sign-in failed. Please try again.")

    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        info = id_token.verify_oauth2_token(
            flow.credentials.id_token, g_requests.Request(),
            cfg["client_id"], clock_skew_in_seconds=10,
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

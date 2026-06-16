"""Google Meet link generation via the Google Calendar API.

A live class becomes a Google Calendar event with conferencing enabled, which
makes Google mint a Meet link. We store that link on the LiveClass.

Setup (one time):
  1. In Google Cloud Console, create a project and enable the *Google Calendar API*.
  2. Create an OAuth client ID of type "Desktop app" and download the JSON to
     ``secrets/client_secret.json`` (path configurable via settings).
  3. Run:  python manage.py google_auth
     This opens a browser once to authorize and caches ``secrets/token.json``.

If credentials are missing or the Google libraries aren't installed, the
functions raise ``GoogleMeetUnavailable`` and the app falls back to letting the
admin paste a Meet link manually — so nothing breaks out of the box.
"""

from __future__ import annotations

import os

from django.conf import settings

# Calendar read/write scope (needed to create events with conferencing).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class GoogleMeetUnavailable(RuntimeError):
    """Raised when Meet links can't be generated (missing libs or creds)."""


def is_configured() -> bool:
    """True if the OAuth client secret and a cached token both exist."""
    return os.path.exists(settings.GOOGLE_OAUTH_CLIENT_SECRET_FILE) and os.path.exists(
        settings.GOOGLE_OAUTH_TOKEN_FILE
    )


def _load_credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise GoogleMeetUnavailable(
            "Google client libraries not installed. Run: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    token_file = settings.GOOGLE_OAUTH_TOKEN_FILE
    if not os.path.exists(token_file):
        raise GoogleMeetUnavailable(
            "Not authorized yet. Run `python manage.py google_auth` once."
        )

    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    if not creds or not creds.valid:
        raise GoogleMeetUnavailable("Stored Google credentials are invalid; re-run google_auth.")
    return creds


def _service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GoogleMeetUnavailable("google-api-python-client not installed.") from exc
    return build("calendar", "v3", credentials=_load_credentials(), cache_discovery=False)


def create_meet_event(live_class) -> tuple[str, str]:
    """Create a Calendar event with a Meet link for ``live_class``.

    Returns ``(meet_link, google_event_id)``.
    Raises ``GoogleMeetUnavailable`` if it can't run.
    """
    service = _service()

    start = live_class.start_time
    end = live_class.end_time
    event_body = {
        "summary": live_class.title,
        "description": live_class.description or f"Live class: {live_class.course.title}",
        "start": {"dateTime": start.isoformat(), "timeZone": settings.TIME_ZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.TIME_ZONE},
        "conferenceData": {
            "createRequest": {
                # requestId must be unique per create call.
                "requestId": f"liveclass-{live_class.pk}-{int(start.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    event = (
        service.events()
        .insert(
            calendarId=settings.GOOGLE_CALENDAR_ID,
            body=event_body,
            conferenceDataVersion=1,
        )
        .execute()
    )

    meet_link = event.get("hangoutLink", "")
    if not meet_link:
        # Fall back to the entryPoints list if hangoutLink isn't populated.
        for ep in event.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break
    return meet_link, event.get("id", "")


def delete_meet_event(google_event_id: str) -> None:
    """Best-effort cleanup of a Calendar event when a class is removed."""
    if not google_event_id:
        return
    try:
        _service().events().delete(
            calendarId=settings.GOOGLE_CALENDAR_ID, eventId=google_event_id
        ).execute()
    except Exception:
        # Cleanup is best effort; never block deletion of the class.
        pass

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

import logging
import os

from django.conf import settings

log = logging.getLogger(__name__)

# Calendar read/write scope (needed to create events with conferencing).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class GoogleMeetUnavailable(RuntimeError):
    """Raised when Meet links can't be generated (missing libs or creds)."""


def _client_configured() -> bool:
    """An OAuth client is available via a Desktop client_secret.json OR the
    Sign-in-with-Google web client settings (reused by the admin connect flow)."""
    return os.path.exists(settings.GOOGLE_OAUTH_CLIENT_SECRET_FILE) or bool(
        getattr(settings, "GOOGLE_LOGIN_CLIENT_ID", "")
    )


def is_configured() -> bool:
    """True if a client is available and the central cached token exists."""
    return _client_configured() and os.path.exists(settings.GOOGLE_OAUTH_TOKEN_FILE)


def _trainer_token_file(live_class):
    """The batch's trainer's cached token, if they connected their own Google.

    When present, events are created on the trainer's calendar so the trainer
    becomes the Meet host. Otherwise we fall back to the central account.
    """
    batch = live_class.batch
    inst_id = batch.instructor_id or getattr(batch.course, "instructor_id", None)
    if not inst_id:
        return None
    path = os.path.join(settings.GOOGLE_TRAINER_TOKEN_DIR, f"{inst_id}.json")
    return path if os.path.exists(path) else None


def _token_file_for_class(live_class):
    """Pick the trainer's token (host = trainer) or fall back to the central one."""
    trainer = _trainer_token_file(live_class)
    if trainer:
        return trainer
    central = settings.GOOGLE_OAUTH_TOKEN_FILE
    return central if os.path.exists(central) else None


def can_create_meet(live_class) -> bool:
    """True if we have a usable token (trainer's or central) to create a Meet."""
    return _client_configured() and _token_file_for_class(live_class) is not None


def _load_credentials(token_file=None):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise GoogleMeetUnavailable(
            "Google client libraries not installed. Run: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    token_file = token_file or settings.GOOGLE_OAUTH_TOKEN_FILE
    if not os.path.exists(token_file):
        raise GoogleMeetUnavailable(
            "Not authorized yet. Connect Google from the admin or Trainer Studio."
        )

    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    if not creds or not creds.valid:
        raise GoogleMeetUnavailable("Stored Google credentials are invalid; reconnect Google.")
    return creds


def _service(token_file=None):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GoogleMeetUnavailable("google-api-python-client not installed.") from exc
    return build("calendar", "v3", credentials=_load_credentials(token_file), cache_discovery=False)


def create_meet_event(live_class) -> tuple[str, str]:
    """Create a Calendar event with a Meet link for ``live_class``.

    Returns ``(meet_link, google_event_id)``.
    Raises ``GoogleMeetUnavailable`` if it can't run.

    The event is created on the batch trainer's calendar when they've connected
    their own Google (so the trainer is the host); otherwise on the central
    account's calendar.
    """
    service = _service(_token_file_for_class(live_class))

    start = live_class.start_time
    end = live_class.end_time
    event_body = {
        "summary": live_class.title,
        "description": live_class.description or f"Live class: {live_class.batch.course.title}",
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

    # Invite the batch's eligible students so Google emails them the Meet link.
    attendees = [{"email": em} for em in live_class.eligible_attendee_emails()]
    if attendees:
        event_body["attendees"] = attendees

    event = (
        service.events()
        .insert(
            calendarId=settings.GOOGLE_CALENDAR_ID,
            body=event_body,
            conferenceDataVersion=1,
            # "all" => Google sends invite emails (with the Meet link) to attendees.
            sendUpdates="all" if attendees else "none",
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


def ensure_meet_link(live_class) -> str:
    """Create + persist a Meet link for ``live_class`` if missing and possible.

    Reads the class's allowed_plans (must already be saved) to invite the right
    students. Returns the link, or "" if it couldn't be generated.
    """
    if live_class.meet_link:
        return live_class.meet_link
    if not can_create_meet(live_class):
        return ""
    try:
        meet_link, event_id = create_meet_event(live_class)
    except GoogleMeetUnavailable as exc:
        log.warning("Meet link not created for LiveClass %s: %s", live_class.pk, exc)
        return ""
    except Exception:
        log.exception("Unexpected error creating Meet link for LiveClass %s", live_class.pk)
        return ""
    if meet_link:
        from .models import LiveClass

        LiveClass.objects.filter(pk=live_class.pk).update(
            meet_link=meet_link, google_event_id=event_id
        )
        live_class.meet_link = meet_link
        live_class.google_event_id = event_id
    return meet_link


def delete_meet_event(google_event_id: str, live_class=None) -> None:
    """Best-effort cleanup of a Calendar event when a class is removed."""
    if not google_event_id:
        return
    token_file = _token_file_for_class(live_class) if live_class is not None else None
    try:
        _service(token_file).events().delete(
            calendarId=settings.GOOGLE_CALENDAR_ID, eventId=google_event_id
        ).execute()
    except Exception:
        # Cleanup is best effort; never block deletion of the class.
        pass

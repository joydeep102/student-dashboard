"""Upload a trainer's video file to YouTube via the YouTube Data API v3.

Videos are uploaded as *unlisted* (configurable) so they only play through the
portal's branded player, never surfacing in public YouTube search.

Setup (one time):
  1. In Google Cloud Console, enable the *YouTube Data API v3* on the same
     project that has your OAuth client (secrets/client_secret.json).
  2. Authorize once (opens a browser, sign in with the channel's owner account):
        python manage.py youtube_auth
     This caches secrets/youtube_token.json.

If the libraries or credentials are missing, ``upload_video`` raises
``YouTubeUnavailable`` and the admin can instead paste a YouTube ID manually.
"""

from __future__ import annotations

import os

from django.conf import settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeUnavailable(RuntimeError):
    """Raised when uploading can't proceed (missing libs or credentials)."""


def _client_configured() -> bool:
    """OAuth client via a Desktop client_secret.json OR the reused
    Sign-in-with-Google web client (admin connect flow)."""
    from accounts.google_config import load

    return os.path.exists(settings.GOOGLE_OAUTH_CLIENT_SECRET_FILE) or bool(load()["client_id"])


def is_configured() -> bool:
    return _client_configured() and os.path.exists(settings.GOOGLE_YOUTUBE_TOKEN_FILE)


def _load_credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover
        raise YouTubeUnavailable(
            "Google client libraries not installed. Run: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    token = settings.GOOGLE_YOUTUBE_TOKEN_FILE
    if not os.path.exists(token):
        raise YouTubeUnavailable("Not authorized yet. Run `python manage.py youtube_auth` once.")

    creds = Credentials.from_authorized_user_file(token, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    if not creds or not creds.valid:
        raise YouTubeUnavailable("Stored YouTube credentials are invalid; re-run youtube_auth.")
    return creds


def upload_video(file_path: str, title: str, description: str = "") -> str:
    """Upload the file at ``file_path`` to YouTube. Returns the video ID.

    Raises ``YouTubeUnavailable`` if it can't run, or the underlying API error
    on a failed upload.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover
        raise YouTubeUnavailable("google-api-python-client not installed.") from exc

    if not os.path.exists(file_path):
        raise YouTubeUnavailable(f"Video file not found: {file_path}")

    youtube = build("youtube", "v3", credentials=_load_credentials(), cache_discovery=False)
    body = {
        "snippet": {"title": title[:100], "description": description, "categoryId": "27"},  # Education
        "status": {
            "privacyStatus": settings.YOUTUBE_UPLOAD_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()
    return response["id"]

"""Send email via the Gmail API, reusing the Sign-in-with-Google OAuth client.

An admin authorizes once ("Connect Gmail" in the admin) which caches a token
with the gmail.send scope to ``secrets/gmail_token.json``; mail is then sent
from that account.
"""

import base64
import os
from email.mime.text import MIMEText

from django.conf import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailUnavailable(RuntimeError):
    """Raised when mail can't be sent (not connected or libs missing)."""


def is_configured() -> bool:
    from accounts.google_config import credentials_for

    return bool(credentials_for("gmail")) and os.path.exists(settings.GOOGLE_GMAIL_TOKEN_FILE)


def _credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover
        raise GmailUnavailable("Google client libraries not installed.") from exc

    token = settings.GOOGLE_GMAIL_TOKEN_FILE
    if not os.path.exists(token):
        raise GmailUnavailable("Gmail isn't connected. Connect it from the admin.")
    creds = Credentials.from_authorized_user_file(token, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    if not creds or not creds.valid:
        raise GmailUnavailable("Stored Gmail credentials are invalid; reconnect Gmail.")
    return creds


def send_email(to_email: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises GmailUnavailable on failure."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GmailUnavailable("google-api-python-client not installed.") from exc

    service = build("gmail", "v1", credentials=_credentials(), cache_discovery=False)
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
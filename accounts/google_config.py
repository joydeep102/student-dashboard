"""Read/write the Google OAuth client credentials used by every Google flow.

Source of truth is ``secrets/google_login.json`` (editable from the admin
"Google API settings" page). Environment variables, when set, take precedence
and make the values read-only in the UI.
"""

import json
import os

from django.conf import settings


def _path():
    return settings.BASE_DIR / "secrets" / "google_login.json"


def load():
    data = {}
    p = _path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or data.get("client_id", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or data.get("client_secret", "")
    redirect_uri = os.environ.get("GOOGLE_LOGIN_REDIRECT_URI") or data.get("redirect_uri", "")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "enabled": bool(client_id and client_secret),
        "from_env": bool(os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_SECRET")),
    }


def save(client_id, client_secret, redirect_uri):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "client_id": (client_id or "").strip(),
                "client_secret": (client_secret or "").strip(),
                "redirect_uri": (redirect_uri or "").strip(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
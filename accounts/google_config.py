"""Google OAuth client credentials, per service.

You can define several OAuth clients and assign which services each one serves
(login, calendar/meet, youtube, gmail) — e.g. one client for Gmail+Calendar and
a separate client for YouTube. Stored in ``secrets/google_clients.json``:

    {"clients": [
        {"client_id": "...", "client_secret": "...", "redirect_uri": "...",
         "services": ["login", "calendar", "gmail"]},
        {"client_id": "...", "client_secret": "...", "redirect_uri": "...",
         "services": ["youtube"]}
    ]}

Environment variables (GOOGLE_CLIENT_ID/SECRET), if set, define a single client
for ALL services and make the UI read-only. The legacy single-client
``secrets/google_login.json`` is auto-migrated to "serves all services".
"""

import json
import os

from django.conf import settings

# (key, label) for each integration that needs a Google client.
SERVICES = [
    ("login", "Sign-in with Google"),
    ("calendar", "Calendar / Meet"),
    ("youtube", "YouTube upload"),
    ("gmail", "Gmail (send mail)"),
]
SERVICE_KEYS = [k for k, _ in SERVICES]


def _path():
    return settings.BASE_DIR / "secrets" / "google_clients.json"


def _legacy_path():
    return settings.BASE_DIR / "secrets" / "google_login.json"


def _norm(c):
    return {
        "client_id": (c.get("client_id") or "").strip(),
        "client_secret": (c.get("client_secret") or "").strip(),
        "redirect_uri": (c.get("redirect_uri") or "").strip(),
        "services": [s for s in (c.get("services") or []) if s in SERVICE_KEYS],
    }


def _env_client():
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET")
    if cid and csec:
        return {
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": os.environ.get("GOOGLE_LOGIN_REDIRECT_URI", ""),
            "services": list(SERVICE_KEYS),
        }
    return None


def load_clients():
    """Return (clients, from_env)."""
    env = _env_client()
    if env:
        return [env], True

    p = _path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            clients = [_norm(c) for c in data.get("clients", []) if (c.get("client_id"))]
            if clients:
                return clients, False
        except Exception:
            pass

    # Migrate a legacy single google_login.json -> one client for all services.
    lp = _legacy_path()
    if lp.exists():
        try:
            d = json.loads(lp.read_text(encoding="utf-8"))
            if d.get("client_id"):
                return [_norm({**d, "services": list(SERVICE_KEYS)})], False
        except Exception:
            pass
    return [], False


def credentials_for(service):
    """The client serving ``service`` (or {} if none assigned)."""
    clients, _ = load_clients()
    for c in clients:
        if service in c["services"] and c["client_id"] and c["client_secret"]:
            return c
    return {}


def is_service_enabled(service):
    return bool(credentials_for(service))


def save_clients(clients):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"clients": [_norm(c) for c in clients if (c.get("client_id"))]}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --- backward-compatible single-client helper (defaults to the login client) ---
def load(service="login"):
    c = credentials_for(service)
    _, from_env = load_clients()
    return {
        "client_id": c.get("client_id", ""),
        "client_secret": c.get("client_secret", ""),
        "redirect_uri": c.get("redirect_uri", ""),
        "enabled": bool(c),
        "from_env": from_env,
    }
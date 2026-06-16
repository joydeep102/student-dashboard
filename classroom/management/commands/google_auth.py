"""One-time OAuth authorization for Google Meet link generation.

Usage:  python manage.py google_auth

Opens a browser, asks you to sign in with the Google account whose calendar
should host the live classes, and caches the resulting token so Meet links can
be created automatically afterwards.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from classroom.google_meet import SCOPES


class Command(BaseCommand):
    help = "Authorize the portal to create Google Meet links (run once)."

    def handle(self, *args, **options):
        client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET_FILE
        token_file = settings.GOOGLE_OAUTH_TOKEN_FILE

        if not os.path.exists(client_secret):
            raise CommandError(
                f"OAuth client secret not found at {client_secret}.\n"
                "Download it from Google Cloud Console (OAuth client ID → Desktop app) "
                "and place it there, or set GOOGLE_OAUTH_CLIENT_SECRET_FILE."
            )

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise CommandError(
                "Missing dependency. Run:\n"
                "  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            ) from exc

        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

        self.stdout.write(self.style.SUCCESS(f"Authorized. Token saved to {token_file}"))
        self.stdout.write("Live classes will now get Google Meet links automatically.")

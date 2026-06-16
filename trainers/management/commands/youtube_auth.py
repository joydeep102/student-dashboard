"""One-time OAuth authorization for uploading trainer videos to YouTube.

Usage:  python manage.py youtube_auth

Opens a browser, asks you to sign in with the YouTube channel's owner account,
and caches the token so approved videos can be uploaded automatically.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from trainers.youtube import SCOPES


class Command(BaseCommand):
    help = "Authorize the portal to upload videos to YouTube (run once)."

    def handle(self, *args, **options):
        client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET_FILE
        token_file = settings.GOOGLE_YOUTUBE_TOKEN_FILE

        if not os.path.exists(client_secret):
            raise CommandError(
                f"OAuth client secret not found at {client_secret}.\n"
                "Download it from Google Cloud Console (OAuth client ID -> Desktop app), "
                "enable the YouTube Data API v3, and place it there."
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
        self.stdout.write("Approved trainer videos will now upload to YouTube automatically.")

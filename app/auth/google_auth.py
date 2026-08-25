"""
Google OAuth2 handling for Gmail + Google Calendar.

Flow:
  1. Download OAuth client credentials from Google Cloud Console
     (APIs & Services -> Credentials -> OAuth client ID -> Desktop app)
     and save as storage/credentials.json (see README).
  2. First run triggers a local browser consent flow; the resulting
     access + refresh tokens are cached at storage/token.json.
  3. Subsequent calls silently refresh the access token using the
     refresh token — no hard-coded secrets, nothing checked into git.

If MOCK_MODE=true (default until you finish setup), this module is
never invoked — the mock tool layer is used instead so the whole
agent pipeline is demonstrable without Google credentials.
"""
from __future__ import annotations
import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from app.config import settings, ALL_SCOPES


class GoogleAuthError(Exception):
    pass


def _load_cached_credentials() -> Optional[Credentials]:
    if not os.path.exists(settings.google_token_path):
        return None
    return Credentials.from_authorized_user_file(settings.google_token_path, ALL_SCOPES)


def get_credentials() -> Credentials:
    """Returns valid Google credentials, refreshing or running the
    interactive consent flow as needed."""
    creds = _load_cached_credentials()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _persist(creds)
            return creds
        except Exception as e:
            raise GoogleAuthError(f"Failed to refresh Google token: {e}") from e

    if not os.path.exists(settings.google_credentials_path):
        raise GoogleAuthError(
            "Missing storage/credentials.json. Download OAuth client "
            "credentials from Google Cloud Console and place them there "
            "(see README setup instructions)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        settings.google_credentials_path, ALL_SCOPES
    )
    creds = flow.run_local_server(port=0)
    _persist(creds)
    return creds


def _persist(creds: Credentials) -> None:
    os.makedirs(os.path.dirname(settings.google_token_path), exist_ok=True)
    with open(settings.google_token_path, "w") as f:
        f.write(creds.to_json())


def gmail_service() -> Resource:
    return build("gmail", "v1", credentials=get_credentials())


def calendar_service() -> Resource:
    return build("calendar", "v3", credentials=get_credentials())

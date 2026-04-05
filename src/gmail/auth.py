"""Gmail OAuth2 authentication.

One-time setup: run `python -m src.gmail.auth` to authorize.
After that, the token is stored and refreshed automatically.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Read-only access to Gmail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_credentials(
    credentials_path: str = "data/gmail_credentials.json",
    token_path: str = "data/gmail_token.json",
) -> Credentials:
    """Get or refresh Gmail API credentials.

    On first run, opens a browser for OAuth consent.
    After that, uses the stored token (refreshing if needed).
    """
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the token for future runs
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


if __name__ == "__main__":
    print("Authorizing Gmail access...")
    print("IMPORTANT: Sign in as projects@casamkali.com (NOT your personal email)")
    print()
    creds = get_gmail_credentials()
    print("Authorization successful! Token saved.")

"""Gmail OAuth2 authentication.

Supports two modes:
1. File-based (local): reads from data/gmail_credentials.json and data/gmail_token.json
2. Environment variable (Railway): reads base64-encoded JSON from GMAIL_CREDENTIALS_B64 and GMAIL_TOKEN_B64

One-time setup: run `python -m src.gmail.auth` locally to authorize.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_credentials(
    credentials_path: str = "data/gmail_credentials.json",
    token_path: str = "data/gmail_token.json",
) -> Credentials:
    """Get or refresh Gmail API credentials.

    Checks environment variables first (for Railway/cloud deployment),
    then falls back to file-based credentials (for local development).
    """
    creds = None

    # Try loading token from environment variable first
    token_b64 = os.environ.get("GMAIL_TOKEN_B64")
    if token_b64:
        token_data = json.loads(base64.b64decode(token_b64).decode())
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    elif os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

            # If running from env var, update the env var with refreshed token
            if token_b64:
                refreshed = json.loads(creds.to_json())
                new_b64 = base64.b64encode(json.dumps(refreshed).encode()).decode()
                os.environ["GMAIL_TOKEN_B64"] = new_b64
        else:
            # Interactive flow — only works locally
            creds_b64 = os.environ.get("GMAIL_CREDENTIALS_B64")
            if creds_b64:
                creds_data = json.loads(base64.b64decode(creds_b64).decode())
                Path("/tmp/gmail_creds.json").write_text(json.dumps(creds_data))
                flow = InstalledAppFlow.from_client_secrets_file("/tmp/gmail_creds.json", SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token to file if running locally
        if not token_b64:
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

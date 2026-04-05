"""Gmail poller — fetches new emails from projects@casamkali.com."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class GmailPoller:
    """Polls Gmail for new messages and returns parsed emails.

    Read-only — never sends, replies, or modifies emails.
    """

    def __init__(self, credentials, message_store):
        self.service = build("gmail", "v1", credentials=credentials)
        self.store = message_store
        self._last_history_id: Optional[str] = None

    def poll_new_messages(self, max_results: int = 20) -> list[dict]:
        """Fetch recent unprocessed emails.

        Returns a list of parsed email dicts.
        """
        try:
            results = self.service.users().messages().list(
                userId="me",
                maxResults=max_results,
                q="is:inbox newer_than:1d",
            ).execute()

            messages = results.get("messages", [])
            if not messages:
                return []

            parsed = []
            for msg_ref in messages:
                msg_id = msg_ref["id"]

                # Skip if already processed
                if self.store.is_email_processed(msg_id):
                    continue

                email = self._fetch_and_parse(msg_id)
                if email:
                    parsed.append(email)

            return parsed

        except Exception:
            logger.exception("Error polling Gmail")
            return []

    def _fetch_and_parse(self, msg_id: str) -> Optional[dict]:
        """Fetch a single email and parse it into a clean dict."""
        try:
            msg = self.service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full",
            ).execute()

            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}

            # Extract body
            body = self._extract_body(msg["payload"])

            # Parse date
            date_str = headers.get("date", "")
            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = datetime.now()

            return {
                "id": msg_id,
                "from": headers.get("from", "unknown"),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": date.isoformat(),
                "body": body[:5000],  # Limit body size
                "snippet": msg.get("snippet", ""),
            }

        except Exception:
            logger.exception("Error fetching email %s", msg_id)
            return None

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from email payload."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Check parts
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Fallback: try HTML
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    # Strip HTML tags
                    return re.sub(r"<[^>]+>", "", html)

        # Nested multipart
        for part in parts:
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        return ""

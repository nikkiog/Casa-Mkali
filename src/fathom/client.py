from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fathom.video/v2"


class FathomClient:
    """Client for the Fathom video meeting API.

    Fetches meeting metadata, recaps (summaries + action items),
    and full transcripts.
    """

    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated request to the Fathom API."""
        url = f"{BASE_URL}{path}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def list_meetings(self, cursor: Optional[str] = None) -> list[dict]:
        """Fetch all meetings with automatic pagination."""
        all_meetings = []
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor

            data = self._request("GET", "/calls", params=params)
            items = data.get("items", [])
            all_meetings.extend(items)

            cursor = data.get("next_cursor")
            if not cursor:
                break

        return all_meetings

    def get_meeting(self, call_id: str) -> dict:
        """Fetch full details for a single meeting including recap."""
        return self._request("GET", f"/calls/{call_id}")

    def get_transcript(self, call_id: str) -> Optional[str]:
        """Fetch the full transcript for a meeting.

        Returns the transcript as a single string, or None if unavailable.
        """
        try:
            data = self._request("GET", f"/calls/{call_id}/transcript")
            # Transcript may come as a list of segments or a string
            if isinstance(data, list):
                lines = []
                for segment in data:
                    speaker = segment.get("speaker", "Unknown")
                    text = segment.get("text", "")
                    lines.append(f"{speaker}: {text}")
                return "\n".join(lines)
            elif isinstance(data, dict):
                segments = data.get("segments", data.get("transcript", []))
                if isinstance(segments, str):
                    return segments
                lines = []
                for segment in segments:
                    speaker = segment.get("speaker", "Unknown")
                    text = segment.get("text", "")
                    lines.append(f"{speaker}: {text}")
                return "\n".join(lines)
            return str(data) if data else None
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.debug("No transcript available for call %s", call_id)
                return None
            raise

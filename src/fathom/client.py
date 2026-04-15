from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fathom.ai/external/v1"


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

    def _request(self, method: str, path: str, **kwargs):
        """Make an authenticated request to the Fathom API."""
        url = f"{BASE_URL}{path}"
        kwargs.setdefault("timeout", 30)
        logger.debug("Fathom API %s %s", method, url)
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def list_meetings(
        self,
        created_after: Optional[str] = None,
    ) -> list[dict]:
        """Fetch meetings with summaries, transcripts, and action items.

        Args:
            created_after: ISO 8601 timestamp — only return meetings created
                after this time. Used for incremental syncing.
        """
        all_meetings = []
        cursor = None
        page = 0
        while True:
            page += 1
            params = {
                "include_summary": "true",
                "include_transcript": "true",
                "include_action_items": "true",
            }
            if cursor:
                params["cursor"] = cursor
            if created_after:
                params["created_after"] = created_after

            logger.info(
                "Fathom API: fetching meetings page %d (created_after=%s)",
                page, created_after,
            )
            data = self._request("GET", "/meetings", params=params)
            items = data.get("items", [])
            logger.info("Fathom API: page %d returned %d meetings", page, len(items))
            all_meetings.extend(items)

            cursor = data.get("next_cursor")
            if not cursor:
                break

        logger.info("Fathom API: total meetings fetched: %d", len(all_meetings))
        return all_meetings

    def get_transcript(self, recording_id: int) -> Optional[str]:
        """Fetch the full transcript for a recording.

        Returns the transcript as a single string, or None if unavailable.
        """
        try:
            data = self._request("GET", f"/recordings/{recording_id}/transcript")
            if isinstance(data, list):
                lines = []
                for segment in data:
                    speaker_obj = segment.get("speaker", {})
                    speaker = speaker_obj.get("display_name", "Unknown") if isinstance(speaker_obj, dict) else str(speaker_obj)
                    text = segment.get("text", "")
                    timestamp = segment.get("timestamp", "")
                    if timestamp:
                        lines.append(f"[{timestamp}] {speaker}: {text}")
                    else:
                        lines.append(f"{speaker}: {text}")
                return "\n".join(lines)
            return str(data) if data else None
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.debug("No transcript available for recording %s", recording_id)
                return None
            raise

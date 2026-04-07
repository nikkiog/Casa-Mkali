from __future__ import annotations

import json
import logging
from typing import Optional

from src.fathom.client import FathomClient
from src.storage.models import MessageStore

logger = logging.getLogger(__name__)


def _parse_meeting_date(meeting: dict) -> Optional[str]:
    """Extract the best available date from a meeting, as YYYY-MM-DD."""
    for field in ("scheduled_start_time", "recording_start_time", "created_at"):
        value = meeting.get(field)
        if value:
            return value[:10]  # "2024-06-15T10:00:00Z" -> "2024-06-15"
    return None


def _format_action_items(meeting: dict) -> Optional[str]:
    """Format action items into readable text."""
    items = meeting.get("action_items", [])
    if not items:
        return None
    lines = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("text", "")
            assignee = item.get("assignee", "")
            line = f"- {text}"
            if assignee:
                line += f" (@{assignee})"
            lines.append(line)
        elif isinstance(item, str):
            lines.append(f"- {item}")
    return "\n".join(lines) if lines else None


def _format_attendees(meeting: dict) -> Optional[str]:
    """Format attendees into readable text."""
    invitees = meeting.get("calendar_invitees", [])
    if not invitees:
        return None
    names = []
    for person in invitees:
        name = person.get("name", "")
        email = person.get("email", "")
        if name and email:
            names.append(f"{name} ({email})")
        elif name:
            names.append(name)
        elif email:
            names.append(email)
    return ", ".join(names) if names else None


def _infer_call_type(meeting: dict) -> str:
    """Categorize a meeting based on its title and metadata."""
    meeting_type = meeting.get("meeting_type", "").lower()
    title = meeting.get("title", "").lower()

    if meeting_type == "sales" or "sales" in title:
        return "Sales Call"
    if "demo" in title:
        return "Demo"
    if "intro" in title or "introduct" in title:
        return "Client Call"
    if "bi-weekly" in title or "biweekly" in title:
        return "Bi-Weekly Status"
    if "weekly" in title:
        return "Weekly Status"
    if "standup" in title or "stand-up" in title or "internal" in title:
        return "Internal"
    if "review" in title:
        return "Internal Review"
    if "support" in title:
        return "Support Call"
    if "partner" in title:
        return "Partner Call"
    if "investor" in title:
        return "Investor Call"
    return "Other Meeting"


class FathomPoller:
    """Polls the Fathom API for new meetings and stores them in the database."""

    def __init__(self, client: FathomClient, message_store: MessageStore):
        self.client = client
        self.store = message_store

    def poll_and_store(self) -> int:
        """Fetch all meetings from Fathom and store new ones.

        Returns the number of newly stored meetings.
        """
        try:
            meetings = self.client.list_meetings()
        except Exception:
            logger.exception("Error fetching meetings from Fathom")
            return 0

        logger.info("Fathom returned %d meetings to process", len(meetings))
        stored = 0

        for meeting in meetings:
            call_id = meeting.get("id") or meeting.get("call_id", "")
            if not call_id:
                continue

            # Skip if already stored
            if self.store.is_meeting_stored(call_id):
                continue

            # Fetch full details and transcript
            try:
                details = self.client.get_meeting(call_id)
            except Exception:
                logger.warning("Could not fetch details for meeting %s", call_id)
                details = meeting

            transcript = None
            try:
                transcript = self.client.get_transcript(call_id)
            except Exception:
                logger.debug("Could not fetch transcript for meeting %s", call_id)

            title = details.get("title") or "Untitled Meeting"
            meeting_date = _parse_meeting_date(details)
            call_type = _infer_call_type(details)
            summary = details.get("default_summary") or details.get("summary", "")
            action_items = _format_action_items(details)
            attendees = _format_attendees(details)
            share_url = details.get("share_url", "")

            if self.store.store_meeting(
                fathom_id=call_id,
                title=title,
                meeting_date=meeting_date,
                call_type=call_type,
                summary=summary,
                action_items=action_items,
                attendees=attendees,
                transcript=transcript,
                share_url=share_url,
                raw_json=json.dumps(details, default=str),
            ):
                stored += 1
                logger.info("Stored meeting: %s (%s)", title[:60], meeting_date)

        return stored

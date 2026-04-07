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
            text = item.get("description", "") or item.get("text", "")
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


def _extract_summary_text(meeting: dict) -> str:
    """Extract summary text from the meeting's default_summary field."""
    summary = meeting.get("default_summary")
    if not summary:
        return ""
    if isinstance(summary, dict):
        return summary.get("markdown_formatted", "") or summary.get("text", "")
    return str(summary)


def _extract_inline_transcript(meeting: dict) -> Optional[str]:
    """Extract transcript from inline transcript field (when include_transcript=true)."""
    transcript = meeting.get("transcript")
    if not transcript:
        return None
    if isinstance(transcript, list):
        lines = []
        for segment in transcript:
            speaker_obj = segment.get("speaker", {})
            speaker = speaker_obj.get("display_name", "Unknown") if isinstance(speaker_obj, dict) else str(speaker_obj)
            text = segment.get("text", "")
            timestamp = segment.get("timestamp", "")
            if timestamp:
                lines.append(f"[{timestamp}] {speaker}: {text}")
            else:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines) if lines else None
    return str(transcript)


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

        The list_meetings call includes summaries, transcripts, and action
        items inline, so no extra per-meeting API calls are needed.

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
            # Use recording_id as the unique identifier
            recording_id = meeting.get("recording_id")
            if not recording_id:
                logger.warning(
                    "Meeting missing recording_id, keys: %s, title: %s",
                    list(meeting.keys())[:10],
                    meeting.get("title", "?")[:60],
                )
                continue

            fathom_id = str(recording_id)

            # Skip if already stored
            if self.store.is_meeting_stored(fathom_id):
                logger.debug("Meeting %s already stored, skipping", fathom_id)
                continue

            # Extract data from the inline response
            title = meeting.get("title") or meeting.get("meeting_title") or "Untitled Meeting"
            meeting_date = _parse_meeting_date(meeting)
            call_type = _infer_call_type(meeting)
            summary = _extract_summary_text(meeting)
            action_items = _format_action_items(meeting)
            attendees = _format_attendees(meeting)
            share_url = meeting.get("share_url", "") or meeting.get("url", "")

            # Use inline transcript; fall back to separate API call if missing
            transcript = _extract_inline_transcript(meeting)
            if not transcript and recording_id:
                try:
                    transcript = self.client.get_transcript(recording_id)
                except Exception:
                    logger.debug("Could not fetch transcript for recording %s", recording_id)

            if self.store.store_meeting(
                fathom_id=fathom_id,
                title=title,
                meeting_date=meeting_date,
                call_type=call_type,
                summary=summary,
                action_items=action_items,
                attendees=attendees,
                transcript=transcript,
                share_url=share_url,
                raw_json=json.dumps(meeting, default=str),
            ):
                stored += 1
                logger.info("Stored meeting: %s (%s)", title[:60], meeting_date)

        return stored

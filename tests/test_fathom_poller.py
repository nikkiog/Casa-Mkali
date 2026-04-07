from __future__ import annotations

import sqlite3

from unittest.mock import patch

from src.fathom.client import FathomClient
from src.fathom.poller import (
    FathomPoller,
    _parse_meeting_date,
    _infer_call_type,
    _extract_summary_text,
    _extract_inline_transcript,
)
from src.storage.database import initialize_schema
from src.storage.models import MessageStore


def _make_store():
    """Create an in-memory SQLite store for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    return MessageStore(conn)


class TestParseMeetingDate:
    def test_prefers_scheduled(self):
        assert _parse_meeting_date({
            "scheduled_start_time": "2024-06-15T10:00:00Z",
            "recording_start_time": "2024-06-15T10:02:00Z",
        }) == "2024-06-15"

    def test_falls_back_to_recording(self):
        assert _parse_meeting_date({
            "recording_start_time": "2024-06-15T10:02:00Z",
        }) == "2024-06-15"

    def test_falls_back_to_created(self):
        assert _parse_meeting_date({
            "created_at": "2024-06-14T08:00:00Z",
        }) == "2024-06-14"

    def test_returns_none_when_empty(self):
        assert _parse_meeting_date({}) is None


class TestInferCallType:
    def test_sales(self):
        assert _infer_call_type({"title": "Sales pitch"}) == "Sales Call"

    def test_demo(self):
        assert _infer_call_type({"title": "Product Demo"}) == "Demo"

    def test_internal(self):
        assert _infer_call_type({"title": "Daily Standup"}) == "Internal"

    def test_fallback(self):
        assert _infer_call_type({"title": "Random Chat"}) == "Other Meeting"


class TestExtractSummaryText:
    def test_dict_with_markdown(self):
        assert _extract_summary_text({
            "default_summary": {"markdown_formatted": "Great meeting."}
        }) == "Great meeting."

    def test_string_summary(self):
        assert _extract_summary_text({
            "default_summary": "Simple summary."
        }) == "Simple summary."

    def test_empty(self):
        assert _extract_summary_text({}) == ""


class TestExtractInlineTranscript:
    def test_list_of_segments(self):
        result = _extract_inline_transcript({
            "transcript": [
                {"speaker": {"display_name": "Alice"}, "text": "Hello", "timestamp": "00:00:05"},
                {"speaker": {"display_name": "Bob"}, "text": "Hi", "timestamp": "00:00:10"},
            ]
        })
        assert "[00:00:05] Alice: Hello" in result
        assert "[00:00:10] Bob: Hi" in result

    def test_none_when_missing(self):
        assert _extract_inline_transcript({}) is None

    def test_none_when_empty_list(self):
        assert _extract_inline_transcript({"transcript": []}) is None


class TestMeetingStorage:
    def test_store_and_search(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="123",
            title="Weekly Standup",
            meeting_date="2024-06-15",
            call_type="Internal",
            summary="Discussed sprint progress and blockers.",
            action_items="- Send report",
            attendees="Alice, Bob",
            transcript="Alice: Let's review the sprint.\nBob: Everything on track.",
            share_url="https://fathom.video/abc",
        )

        results = store.search_meetings("sprint")
        assert len(results) == 1
        assert results[0]["title"] == "Weekly Standup"

    def test_search_transcript(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="456",
            title="Client Sync",
            meeting_date="2024-06-16",
            call_type="Client Call",
            summary="Reviewed deliverables.",
            action_items=None,
            attendees="Charlie",
            transcript="Charlie: The branding assets look great.",
            share_url=None,
        )

        results = store.search_meetings("branding")
        assert len(results) == 1
        assert results[0]["fathom_id"] == "456"

    def test_duplicate_prevention(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="789", title="Test", meeting_date="2024-06-17",
            call_type="Other Meeting", summary="Test meeting.",
            action_items=None, attendees=None, transcript=None, share_url=None,
        )
        store.store_meeting(
            fathom_id="789", title="Test Duplicate", meeting_date="2024-06-17",
            call_type="Other Meeting", summary="Duplicate.",
            action_items=None, attendees=None, transcript=None, share_url=None,
        )
        assert store.get_meeting_count() == 1

    def test_is_meeting_stored(self):
        store = _make_store()
        assert not store.is_meeting_stored("999")
        store.store_meeting(
            fathom_id="999", title="Stored", meeting_date=None,
            call_type=None, summary=None, action_items=None,
            attendees=None, transcript=None, share_url=None,
        )
        assert store.is_meeting_stored("999")


class TestFathomPoller:
    def test_poll_and_store_new_meetings(self):
        store = _make_store()
        client = FathomClient("test-key")

        meetings_list = [
            {
                "recording_id": 1,
                "title": "Standup",
                "created_at": "2024-06-15T10:00:00Z",
                "default_summary": {"markdown_formatted": "Quick standup."},
                "action_items": [],
                "calendar_invitees": [],
                "transcript": [
                    {"speaker": {"display_name": "Alice"}, "text": "Morning!", "timestamp": "00:00:01"}
                ],
                "share_url": "https://fathom.video/1",
            },
            {
                "recording_id": 2,
                "title": "Client Call",
                "created_at": "2024-06-16T10:00:00Z",
                "default_summary": {"markdown_formatted": "Reviewed project status."},
                "action_items": [{"description": "Send proposal", "assignee": "Nikki"}],
                "calendar_invitees": [{"name": "Client", "email": "client@test.com"}],
                "transcript": None,
                "share_url": "https://fathom.video/2",
            },
        ]

        with patch.object(client, "list_meetings", return_value=meetings_list), \
             patch.object(client, "get_transcript", return_value="Speaker: Hello"):
            poller = FathomPoller(client, store)
            stored = poller.poll_and_store()

        assert stored == 2
        assert store.get_meeting_count() == 2

    def test_skips_already_stored(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="1", title="Already Stored", meeting_date="2024-06-15",
            call_type="Internal", summary="Old meeting.",
            action_items=None, attendees=None, transcript=None, share_url=None,
        )

        client = FathomClient("test-key")
        meetings_list = [{"recording_id": 1, "title": "Already Stored"}]

        with patch.object(client, "list_meetings", return_value=meetings_list):
            poller = FathomPoller(client, store)
            stored = poller.poll_and_store()

        assert stored == 0
        assert store.get_meeting_count() == 1

from __future__ import annotations

import sqlite3

from unittest.mock import MagicMock, patch

from src.fathom.client import FathomClient
from src.fathom.poller import FathomPoller, _parse_meeting_date, _infer_call_type
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


class TestMeetingStorage:
    def test_store_and_search(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="call_123",
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
            fathom_id="call_456",
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
        assert results[0]["fathom_id"] == "call_456"

    def test_duplicate_prevention(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="call_789",
            title="Test",
            meeting_date="2024-06-17",
            call_type="Other Meeting",
            summary="Test meeting.",
            action_items=None,
            attendees=None,
            transcript=None,
            share_url=None,
        )
        # Second insert should not raise
        store.store_meeting(
            fathom_id="call_789",
            title="Test Duplicate",
            meeting_date="2024-06-17",
            call_type="Other Meeting",
            summary="Duplicate.",
            action_items=None,
            attendees=None,
            transcript=None,
            share_url=None,
        )
        assert store.get_meeting_count() == 1

    def test_is_meeting_stored(self):
        store = _make_store()
        assert not store.is_meeting_stored("call_999")
        store.store_meeting(
            fathom_id="call_999",
            title="Stored",
            meeting_date=None,
            call_type=None,
            summary=None,
            action_items=None,
            attendees=None,
            transcript=None,
            share_url=None,
        )
        assert store.is_meeting_stored("call_999")


class TestFathomPoller:
    def test_poll_and_store_new_meetings(self):
        store = _make_store()
        client = FathomClient("test-key")

        meetings_list = [
            {"id": "call_1", "title": "Standup", "created_at": "2024-06-15T10:00:00Z"},
            {"id": "call_2", "title": "Client Call", "created_at": "2024-06-16T10:00:00Z"},
        ]
        detail_1 = {
            "id": "call_1", "title": "Standup",
            "created_at": "2024-06-15T10:00:00Z",
            "default_summary": "Quick standup.",
            "action_items": [],
            "calendar_invitees": [],
        }
        detail_2 = {
            "id": "call_2", "title": "Client Call",
            "created_at": "2024-06-16T10:00:00Z",
            "default_summary": "Reviewed project status.",
            "action_items": [{"text": "Send proposal", "assignee": "Nikki"}],
            "calendar_invitees": [{"name": "Client", "email": "client@test.com"}],
        }

        with patch.object(client, "list_meetings", return_value=meetings_list), \
             patch.object(client, "get_meeting", side_effect=[detail_1, detail_2]), \
             patch.object(client, "get_transcript", return_value="Speaker: Hello"):
            poller = FathomPoller(client, store)
            stored = poller.poll_and_store()

        assert stored == 2
        assert store.get_meeting_count() == 2

    def test_skips_already_stored(self):
        store = _make_store()
        store.store_meeting(
            fathom_id="call_1",
            title="Already Stored",
            meeting_date="2024-06-15",
            call_type="Internal",
            summary="Old meeting.",
            action_items=None,
            attendees=None,
            transcript=None,
            share_url=None,
        )

        client = FathomClient("test-key")
        meetings_list = [{"id": "call_1", "title": "Already Stored"}]

        with patch.object(client, "list_meetings", return_value=meetings_list):
            poller = FathomPoller(client, store)
            stored = poller.poll_and_store()

        assert stored == 0
        assert store.get_meeting_count() == 1

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.airtable.client import AirtableClient
from src.airtable.mapper import (
    build_airtable_fields,
    build_full_notes,
    extract_tags,
    infer_call_type,
    parse_meeting_date,
)


class TestInferCallType:
    def test_intro_call(self):
        assert infer_call_type({"title": "Intro Call with Acme"}) == "Client Call"

    def test_demo(self):
        assert infer_call_type({"title": "Product Demo for Client"}) == "Demo"

    def test_internal_standup(self):
        assert infer_call_type({"title": "Daily Standup"}) == "Internal"

    def test_fallback_to_other(self):
        assert infer_call_type({"title": "Random Chat"}) == "Other Meeting"

    def test_uses_meeting_type_field(self):
        assert (
            infer_call_type({"title": "Quick sync", "meeting_type": "sales"})
            == "Sales Call"
        )

    def test_sales_call(self):
        assert infer_call_type({"title": "Sales pitch to Widget Inc"}) == "Sales Call"

    def test_review(self):
        assert infer_call_type({"title": "Q2 Performance Review"}) == "Internal Review"

    def test_weekly_status(self):
        assert infer_call_type({"title": "Project Weekly Sync"}) == "Weekly Status"

    def test_biweekly(self):
        assert infer_call_type({"title": "Skoop Bi-Weekly Call"}) == "Bi-Weekly Status"

    def test_support(self):
        assert infer_call_type({"title": "Support ticket #123"}) == "Support Call"

    def test_partner(self):
        assert infer_call_type({"title": "Partner sync"}) == "Partner Call"

    def test_investor(self):
        assert infer_call_type({"title": "Investor meeting Q3"}) == "Investor Call"


class TestExtractTags:
    def test_action_items_present(self):
        tags = extract_tags({"action_items": [{"text": "Do something"}]})
        assert "Action Items" in tags

    def test_keyword_matching(self):
        tags = extract_tags({
            "title": "Sprint Retrospective",
            "default_summary": "Reviewed sprint goals",
        })
        assert "sprint" in tags
        assert "retrospective" in tags
        assert "review" in tags

    def test_no_tags_for_generic_meeting(self):
        tags = extract_tags({"title": "Quick Chat"})
        assert tags == []

    def test_action_items_as_strings(self):
        tags = extract_tags({"action_items": ["Send follow-up email"]})
        assert "Action Items" in tags
        assert "Follow-Up Needed" in tags

    def test_multiple_keyword_sources(self):
        tags = extract_tags({
            "title": "Demo call",
            "default_summary": "Discussed marketing strategy and campaign plans",
        })
        assert "demo" in tags
        assert "marketing" in tags
        assert "strategy" in tags
        assert "campaign" in tags


class TestParseMeetingDate:
    def test_prefers_scheduled_start(self):
        meeting = {
            "scheduled_start_time": "2024-06-15T10:00:00Z",
            "recording_start_time": "2024-06-15T10:02:00Z",
            "created_at": "2024-06-14T08:00:00Z",
        }
        assert parse_meeting_date(meeting) == "2024-06-15"

    def test_falls_back_to_recording(self):
        meeting = {"recording_start_time": "2024-06-15T10:02:00Z"}
        assert parse_meeting_date(meeting) == "2024-06-15"

    def test_falls_back_to_created(self):
        meeting = {"created_at": "2024-06-14T08:00:00Z"}
        assert parse_meeting_date(meeting) == "2024-06-14"

    def test_returns_none_when_empty(self):
        assert parse_meeting_date({}) is None


class TestBuildFullNotes:
    def test_includes_summary(self):
        notes = build_full_notes({"default_summary": "Great meeting about Q3."})
        assert "## Summary" in notes
        assert "Great meeting about Q3." in notes

    def test_includes_action_items(self):
        notes = build_full_notes({
            "action_items": [
                {"text": "Send report", "assignee": "Alice"},
                {"text": "Book room"},
            ]
        })
        assert "## Action Items" in notes
        assert "- Send report (@Alice)" in notes
        assert "- Book room" in notes

    def test_includes_attendees(self):
        notes = build_full_notes({
            "calendar_invitees": [
                {"name": "Bob", "email": "bob@example.com"},
            ]
        })
        assert "## Attendees" in notes
        assert "Bob (bob@example.com)" in notes

    def test_includes_recording_link(self):
        notes = build_full_notes({"share_url": "https://fathom.video/abc"})
        assert "## Recording" in notes
        assert "https://fathom.video/abc" in notes

    def test_empty_meeting(self):
        assert build_full_notes({}) == ""


class TestBuildAirtableFields:
    def test_basic_mapping(self):
        meeting = {
            "title": "Weekly Standup",
            "scheduled_start_time": "2024-06-15T10:00:00Z",
            "default_summary": "Discussed project status.",
            "action_items": [],
            "calendar_invitees": [],
        }
        fields = build_airtable_fields(
            meeting, team_member_ids=["recABC"], client_ids=[]
        )
        assert fields["Meeting Name"] == "Weekly Standup"
        assert fields["Meeting Date"] == "2024-06-15"
        assert fields["Team Members"] == ["recABC"]
        assert "Client" not in fields
        assert fields["Type of Call"] == "Internal"  # "standup" matches Internal

    def test_untitled_meeting_fallback(self):
        fields = build_airtable_fields({}, team_member_ids=[], client_ids=[])
        assert fields["Meeting Name"] == "Untitled Meeting"

    def test_client_ids_included(self):
        fields = build_airtable_fields(
            {"title": "Client sync"},
            team_member_ids=[],
            client_ids=["recCLIENT1"],
        )
        assert fields["Client"] == ["recCLIENT1"]

    def test_topic_matches_meeting_name(self):
        fields = build_airtable_fields(
            {"title": "Budget Review"},
            team_member_ids=[],
            client_ids=[],
        )
        assert fields["Topic"] == "Budget Review"


class TestAirtableClient:
    def test_list_all_records_single_page(self):
        client = AirtableClient("test-token", "appTEST")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "records": [{"id": "rec1", "fields": {"Name": "Alice"}}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "request", return_value=mock_response):
            records = client.list_all_records("tblTEST", fields=["Name"])

        assert len(records) == 1
        assert records[0]["fields"]["Name"] == "Alice"

    def test_create_records_batching(self):
        client = AirtableClient("test-token", "appTEST")

        # 12 records should produce 2 batches (10 + 2)
        records = [{"fields": {"Name": f"Meeting {i}"}} for i in range(12)]

        batch1_response = MagicMock()
        batch1_response.json.return_value = {
            "records": [{"id": f"rec{i}"} for i in range(10)]
        }
        batch1_response.raise_for_status = MagicMock()

        batch2_response = MagicMock()
        batch2_response.json.return_value = {
            "records": [{"id": f"rec{i}"} for i in range(10, 12)]
        }
        batch2_response.raise_for_status = MagicMock()

        with patch.object(
            client.session,
            "request",
            side_effect=[batch1_response, batch2_response],
        ):
            created = client.create_records("tblTEST", records)

        assert len(created) == 12

    def test_auth_header(self):
        client = AirtableClient("pat-my-token", "appTEST")
        assert client.session.headers["Authorization"] == "Bearer pat-my-token"

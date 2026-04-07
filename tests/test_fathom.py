from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.fathom.client import FathomClient


class TestFathomClient:
    def test_list_meetings_single_page(self):
        client = FathomClient("test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [{"title": "Meeting 1", "recording_id": 1}],
            "next_cursor": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "request", return_value=mock_response):
            meetings = client.list_meetings()

        assert len(meetings) == 1
        assert meetings[0]["title"] == "Meeting 1"

    def test_list_meetings_pagination(self):
        client = FathomClient("test-key")
        page1 = MagicMock()
        page1.json.return_value = {
            "items": [{"title": "Meeting 1", "recording_id": 1}],
            "next_cursor": "cursor_abc",
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.json.return_value = {
            "items": [{"title": "Meeting 2", "recording_id": 2}],
            "next_cursor": None,
        }
        page2.raise_for_status = MagicMock()

        with patch.object(client.session, "request", side_effect=[page1, page2]):
            meetings = client.list_meetings()

        assert len(meetings) == 2
        assert meetings[0]["title"] == "Meeting 1"
        assert meetings[1]["title"] == "Meeting 2"

    def test_list_meetings_empty(self):
        client = FathomClient("test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [],
            "next_cursor": None,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "request", return_value=mock_response):
            meetings = client.list_meetings()

        assert meetings == []

    def test_api_key_in_headers(self):
        client = FathomClient("my-secret-key")
        assert client.session.headers["X-Api-Key"] == "my-secret-key"

    def test_list_meetings_includes_params(self):
        client = FathomClient("test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = {"items": [], "cursor": None}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "request", return_value=mock_response) as mock_req:
            client.list_meetings()

        call_kwargs = mock_req.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params["include_summary"] == "true"
        assert params["include_transcript"] == "true"
        assert params["include_action_items"] == "true"

    def test_get_transcript(self):
        client = FathomClient("test-key")
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "speaker": {"display_name": "Alice"},
                "text": "Hello everyone",
                "timestamp": "00:00:05",
            },
            {
                "speaker": {"display_name": "Bob"},
                "text": "Hi Alice",
                "timestamp": "00:00:10",
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch.object(client.session, "request", return_value=mock_response):
            transcript = client.get_transcript(123)

        assert "[00:00:05] Alice: Hello everyone" in transcript
        assert "[00:00:10] Bob: Hi Alice" in transcript

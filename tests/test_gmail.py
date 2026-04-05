from unittest.mock import MagicMock, patch

from src.gmail.parser import format_email_for_ai
from src.gmail.poller import GmailPoller


class TestGmailParser:
    def test_format_email_for_ai(self):
        email = {
            "id": "msg-123",
            "subject": "Q1 Planning",
            "from": "alice@example.com",
            "to": "team@example.com",
            "cc": "bob@example.com",
            "date": "Mon, 10 Feb 2026 10:00:00 -0800",
            "snippet": "Let's discuss the Q1 roadmap in tomorrow's meeting.",
        }
        result = format_email_for_ai(email)
        assert "alice@example.com" in result
        assert "Q1 Planning" in result
        assert "bob@example.com" in result
        assert "Q1 roadmap" in result

    def test_format_email_without_cc(self):
        email = {
            "id": "msg-456",
            "subject": "Hello",
            "from": "alice@example.com",
            "to": "team@example.com",
            "cc": "",
            "date": "Mon, 10 Feb 2026 10:00:00 -0800",
            "snippet": "Hi there.",
        }
        result = format_email_for_ai(email)
        assert "CC:" not in result


class TestGmailPoller:
    def _make_poller(self, task_store, mock_service=None):
        """Create a GmailPoller with a mocked Gmail service."""
        with patch("src.gmail.poller.build") as mock_build:
            mock_build.return_value = mock_service or MagicMock()
            poller = GmailPoller(credentials=MagicMock(), task_store=task_store)
        return poller

    def test_first_run_sets_baseline(self, task_store):
        mock_service = MagicMock()
        mock_service.users.return_value.getProfile.return_value.execute.return_value = {
            "historyId": "12345"
        }

        poller = self._make_poller(task_store, mock_service)
        messages = poller.poll_new_messages()

        assert messages == []
        assert task_store.get_gmail_history_id() == "12345"

    def test_poll_finds_new_messages(self, task_store):
        task_store.set_gmail_history_id("100")

        mock_service = MagicMock()
        mock_service.users.return_value.history.return_value.list.return_value.execute.return_value = {
            "historyId": "200",
            "history": [
                {
                    "messagesAdded": [
                        {"message": {"id": "msg-abc"}},
                    ]
                }
            ],
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg-abc",
            "snippet": "Please review the budget",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "To", "value": "team@example.com"},
                    {"name": "Subject", "value": "Budget Review"},
                    {"name": "Date", "value": "2026-02-10"},
                ]
            },
        }

        poller = self._make_poller(task_store, mock_service)
        messages = poller.poll_new_messages()

        assert len(messages) == 1
        assert messages[0]["subject"] == "Budget Review"
        assert messages[0]["from"] == "alice@example.com"
        assert task_store.get_gmail_history_id() == "200"

    def test_poll_skips_already_processed(self, task_store):
        task_store.set_gmail_history_id("100")
        task_store.mark_message_processed("gmail", "msg-already-seen")

        mock_service = MagicMock()
        mock_service.users.return_value.history.return_value.list.return_value.execute.return_value = {
            "historyId": "200",
            "history": [
                {
                    "messagesAdded": [
                        {"message": {"id": "msg-already-seen"}},
                    ]
                }
            ],
        }

        poller = self._make_poller(task_store, mock_service)
        messages = poller.poll_new_messages()

        assert len(messages) == 0

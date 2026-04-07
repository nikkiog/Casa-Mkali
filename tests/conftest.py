import sqlite3

import pytest

from src.storage.database import initialize_schema
from src.storage.models import MessageStore


@pytest.fixture
def test_db():
    """In-memory SQLite database with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def task_store(test_db):
    """TaskStore backed by an in-memory database."""
    return MessageStore(test_db)


@pytest.fixture
def mock_slack_bot():
    """Mock SlackBot that records posted messages."""
    class MockSlackBot:
        def __init__(self):
            self.posted_messages = []

        def post_update(self, channel_id, text, blocks=None):
            self.posted_messages.append({
                "channel_id": channel_id,
                "text": text,
                "blocks": blocks,
            })

    return MockSlackBot()

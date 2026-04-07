import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL,
    channel_name    TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    user_name       TEXT,
    text            TEXT NOT NULL,
    ts              TEXT NOT NULL UNIQUE,
    thread_ts       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_channel_messages_channel
    ON channel_messages(channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_messages_ts
    ON channel_messages(ts);

CREATE TABLE IF NOT EXISTS sync_state (
    channel_id      TEXT PRIMARY KEY,
    oldest_ts       TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer_ts       TEXT,
    channel_id      TEXT,
    source          TEXT NOT NULL DEFAULT 'mention',
    feedback        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_question_log_created
    ON question_log(created_at);

CREATE TABLE IF NOT EXISTS team_updates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    user_name       TEXT,
    update_text     TEXT NOT NULL,
    channel_id      TEXT,
    thread_ts       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_team_updates_created
    ON team_updates(created_at);
CREATE INDEX IF NOT EXISTS idx_team_updates_user
    ON team_updates(user_id);

CREATE TABLE IF NOT EXISTS emails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id        TEXT NOT NULL UNIQUE,
    from_addr       TEXT NOT NULL,
    to_addr         TEXT,
    subject         TEXT NOT NULL,
    body            TEXT,
    snippet         TEXT,
    email_date      TEXT NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_emails_date
    ON emails(email_date);

CREATE TABLE IF NOT EXISTS meetings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fathom_id       TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    meeting_date    TEXT,
    call_type       TEXT,
    summary         TEXT,
    action_items    TEXT,
    attendees       TEXT,
    transcript      TEXT,
    share_url       TEXT,
    raw_json        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_meetings_date
    ON meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_meetings_fathom_id
    ON meetings(fathom_id);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and Row factory.

    Uses check_same_thread=False because Slack Bolt dispatches events
    across multiple threads. WAL mode ensures safe concurrent access.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist."""
    conn.executescript(SCHEMA)
    conn.commit()

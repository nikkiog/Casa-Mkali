from __future__ import annotations

import sqlite3
from typing import Optional


class MessageStore:
    """Stores and searches indexed Slack channel messages."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def store_message(
        self,
        channel_id: str,
        channel_name: str,
        user_id: str,
        user_name: Optional[str],
        text: str,
        ts: str,
        thread_ts: Optional[str] = None,
    ) -> bool:
        """Store a channel message. Returns True if inserted, False if duplicate."""
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO channel_messages
                    (channel_id, channel_name, user_id, user_name, text, ts, thread_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel_id, channel_name, user_id, user_name, text, ts, thread_ts),
            )
            self.conn.commit()
            return self.conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False

    def search_messages(self, query: str, limit: int = 50) -> list[dict]:
        """Search messages by keyword matching.

        Splits the query into words and matches messages containing all words.
        Returns most recent matches first.
        """
        words = query.lower().split()
        if not words:
            return []

        # Build WHERE clause: each word must appear in the text
        conditions = " AND ".join(["LOWER(text) LIKE ?"] * len(words))
        params = [f"%{word}%" for word in words]
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
            FROM channel_messages
            WHERE {conditions}
            ORDER BY ts DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_messages(
        self, channel_id: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """Get recent messages, optionally filtered by channel."""
        if channel_id:
            rows = self.conn.execute(
                """
                SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
                FROM channel_messages
                WHERE channel_id = ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
                FROM channel_messages
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_message_count(self) -> int:
        """Return the total number of indexed messages."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM channel_messages").fetchone()
        return row["cnt"]

    def get_channel_list(self) -> list[dict]:
        """Return distinct channels with message counts."""
        rows = self.conn.execute(
            """
            SELECT channel_id, channel_name, COUNT(*) as message_count
            FROM channel_messages
            GROUP BY channel_id, channel_name
            ORDER BY message_count DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_messages_by_channel_name(
        self, channel_name: str, limit: int = 50
    ) -> list[dict]:
        """Get recent messages from a channel matched by name (case-insensitive)."""
        rows = self.conn.execute(
            """
            SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
            FROM channel_messages
            WHERE LOWER(channel_name) = LOWER(?)
            ORDER BY ts DESC
            LIMIT ?
            """,
            (channel_name, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_sync_state(self, channel_id: str) -> Optional[str]:
        """Get the oldest timestamp synced for a channel."""
        row = self.conn.execute(
            "SELECT oldest_ts FROM sync_state WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        return row["oldest_ts"] if row else None

    def set_sync_state(self, channel_id: str, oldest_ts: str) -> None:
        """Record the oldest timestamp synced for a channel."""
        self.conn.execute(
            """
            INSERT INTO sync_state (channel_id, oldest_ts, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(channel_id) DO UPDATE SET
                oldest_ts = excluded.oldest_ts,
                updated_at = datetime('now')
            """,
            (channel_id, oldest_ts),
        )
        self.conn.commit()

    # --- Question logging ---

    def log_question(
        self,
        user_id: str,
        question: str,
        source: str = "mention",
        channel_id: Optional[str] = None,
        answer_ts: Optional[str] = None,
    ) -> int:
        """Log a question that was asked. Returns the log ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO question_log (user_id, question, source, channel_id, answer_ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, question, source, channel_id, answer_ts),
        )
        self.conn.commit()
        return cursor.lastrowid

    def set_question_feedback(self, question_id: int, feedback: str) -> None:
        """Record thumbs up/down feedback for a question."""
        self.conn.execute(
            "UPDATE question_log SET feedback = ? WHERE id = ?",
            (feedback, question_id),
        )
        self.conn.commit()

    def set_answer_ts(self, question_id: int, answer_ts: str) -> None:
        """Record the message timestamp of the bot's answer."""
        self.conn.execute(
            "UPDATE question_log SET answer_ts = ? WHERE id = ?",
            (answer_ts, question_id),
        )
        self.conn.commit()

    def get_question_by_answer_ts(self, answer_ts: str) -> Optional[dict]:
        """Look up a question by its answer message timestamp."""
        row = self.conn.execute(
            "SELECT * FROM question_log WHERE answer_ts = ?",
            (answer_ts,),
        ).fetchone()
        return dict(row) if row else None

    def get_top_questions(self, limit: int = 20) -> list[dict]:
        """Get the most frequently asked question keywords."""
        rows = self.conn.execute(
            """
            SELECT question, COUNT(*) as ask_count,
                   SUM(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END) as thumbs_up,
                   SUM(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END) as thumbs_down
            FROM question_log
            GROUP BY LOWER(question)
            ORDER BY ask_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_question_stats(self) -> dict:
        """Get overall question statistics."""
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total_questions,
                SUM(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END) as total_thumbs_up,
                SUM(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END) as total_thumbs_down,
                COUNT(DISTINCT user_id) as unique_users
            FROM question_log
            """
        ).fetchone()
        return dict(row)

    # --- Personalized digest ---

    def get_recent_messages_for_channels(
        self,
        channel_ids: list[str],
        hours: int = 24,
        limit: int = 200,
    ) -> list[dict]:
        """Get recent messages from specific channels within a time window."""
        import time as _time
        cutoff_ts = str(_time.time() - (hours * 3600))
        if not channel_ids:
            return []
        placeholders = ",".join(["?"] * len(channel_ids))
        params = channel_ids + [cutoff_ts, limit]
        rows = self.conn.execute(
            f"""
            SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
            FROM channel_messages
            WHERE channel_id IN ({placeholders})
              AND ts > ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_messages_by_user(
        self,
        user_id: str,
        hours: int = 168,
        limit: int = 30,
    ) -> list[dict]:
        """Get recent messages sent BY a specific user (for style inference)."""
        import time as _time
        cutoff_ts = str(_time.time() - (hours * 3600))
        rows = self.conn.execute(
            """
            SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
            FROM channel_messages
            WHERE user_id = ?
              AND ts > ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (user_id, cutoff_ts, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_messages_mentioning_user(
        self,
        user_id: str,
        hours: int = 24,
        limit: int = 50,
    ) -> list[dict]:
        """Get recent messages that @mention a specific user."""
        import time as _time
        cutoff_ts = str(_time.time() - (hours * 3600))
        mention_pattern = f"%<@{user_id}>%"
        rows = self.conn.execute(
            """
            SELECT channel_id, channel_name, user_id, user_name, text, ts, thread_ts
            FROM channel_messages
            WHERE text LIKE ?
              AND ts > ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (mention_pattern, cutoff_ts, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Team updates (user-submitted memory) ---

    def save_team_update(
        self,
        user_id: str,
        user_name: Optional[str],
        update_text: str,
        channel_id: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> int:
        """Save a team member's update/status. Returns the update ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO team_updates (user_id, user_name, update_text, channel_id, thread_ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, user_name, update_text, channel_id, thread_ts),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_updates(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Get recent team updates within a time window."""
        import time as _time
        cutoff = _time.time() - (hours * 3600)
        rows = self.conn.execute(
            """
            SELECT id, user_id, user_name, update_text, channel_id, created_at
            FROM team_updates
            WHERE strftime('%s', created_at) > ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(int(cutoff)), limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_updates_for_user(
        self, user_id: str, hours: int = 24, limit: int = 20
    ) -> list[dict]:
        """Get recent updates submitted by a specific user."""
        import time as _time
        cutoff = _time.time() - (hours * 3600)
        rows = self.conn.execute(
            """
            SELECT id, user_id, user_name, update_text, channel_id, created_at
            FROM team_updates
            WHERE strftime('%s', created_at) > ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (str(int(cutoff)), limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Email storage ---

    def store_email(
        self,
        gmail_id: str,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
        snippet: str,
        email_date: str,
    ) -> bool:
        """Store an email. Returns True if inserted, False if duplicate."""
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO emails
                    (gmail_id, from_addr, to_addr, subject, body, snippet, email_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (gmail_id, from_addr, to_addr, subject, body, snippet, email_date),
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def is_email_processed(self, gmail_id: str) -> bool:
        """Check if an email has already been stored."""
        row = self.conn.execute(
            "SELECT 1 FROM emails WHERE gmail_id = ?",
            (gmail_id,),
        ).fetchone()
        return row is not None

    def search_emails(self, query: str, limit: int = 20) -> list[dict]:
        """Search emails by keyword matching in subject and body."""
        words = query.lower().split()
        if not words:
            return []

        conditions = " AND ".join(
            ["(LOWER(subject) LIKE ? OR LOWER(body) LIKE ?)"] * len(words)
        )
        params = []
        for word in words:
            params.extend([f"%{word}%", f"%{word}%"])
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT gmail_id, from_addr, to_addr, subject, body, snippet, email_date
            FROM emails
            WHERE {conditions}
            ORDER BY email_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_emails(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Get recent emails within a time window."""
        import time as _time
        cutoff = _time.time() - (hours * 3600)
        rows = self.conn.execute(
            """
            SELECT gmail_id, from_addr, to_addr, subject, body, snippet, email_date
            FROM emails
            WHERE strftime('%s', email_date) > ?
            ORDER BY email_date DESC
            LIMIT ?
            """,
            (str(int(cutoff)), limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_email_count(self) -> int:
        """Return the total number of indexed emails."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM emails").fetchone()
        return row["cnt"]

    def get_email_by_id(self, gmail_id: str) -> Optional[dict]:
        """Get a full email by its Gmail ID, including body."""
        row = self.conn.execute(
            """
            SELECT gmail_id, from_addr, to_addr, subject, body, snippet, email_date
            FROM emails
            WHERE gmail_id = ?
            """,
            (gmail_id,),
        ).fetchone()
        return dict(row) if row else None

    # --- Weekly to-dos ---

    def get_latest_weekly_todos(self) -> Optional[dict]:
        """Get the most recent weekly to-do message from #casageneral.

        These are posted on Mondays and start with '*Hi team*' and contain
        'to-dos by client'.
        """
        row = self.conn.execute(
            """
            SELECT channel_id, channel_name, user_id, user_name, text, ts
            FROM channel_messages
            WHERE LOWER(channel_name) = 'casageneral'
              AND text LIKE '*Hi team*%'
              AND LOWER(text) LIKE '%to-dos%'
            ORDER BY ts DESC
            LIMIT 1
            """,
        ).fetchone()
        return dict(row) if row else None

    # --- Meeting storage (Fathom) ---

    def store_meeting(
        self,
        fathom_id: str,
        title: str,
        meeting_date: Optional[str],
        call_type: Optional[str],
        summary: Optional[str],
        action_items: Optional[str],
        attendees: Optional[str],
        transcript: Optional[str],
        share_url: Optional[str],
        raw_json: Optional[str] = None,
    ) -> bool:
        """Store a Fathom meeting. Returns True if inserted, False if duplicate."""
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO meetings
                    (fathom_id, title, meeting_date, call_type, summary,
                     action_items, attendees, transcript, share_url, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fathom_id, title, meeting_date, call_type, summary,
                 action_items, attendees, transcript, share_url, raw_json),
            )
            self.conn.commit()
            return self.conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False

    def is_meeting_stored(self, fathom_id: str) -> bool:
        """Check if a meeting has already been stored."""
        row = self.conn.execute(
            "SELECT 1 FROM meetings WHERE fathom_id = ?",
            (fathom_id,),
        ).fetchone()
        return row is not None

    def search_meetings(self, query: str, limit: int = 20) -> list[dict]:
        """Search meetings by keyword matching in title, summary, transcript, and action items."""
        words = query.lower().split()
        if not words:
            return []

        conditions = " AND ".join(
            [
                "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? "
                "OR LOWER(transcript) LIKE ? OR LOWER(action_items) LIKE ?)"
            ]
            * len(words)
        )
        params = []
        for word in words:
            params.extend([f"%{word}%"] * 4)
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT fathom_id, title, meeting_date, call_type, summary,
                   action_items, attendees, transcript, share_url
            FROM meetings
            WHERE {conditions}
            ORDER BY meeting_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_meetings(self, limit: int = 20) -> list[dict]:
        """Get the most recent meetings."""
        rows = self.conn.execute(
            """
            SELECT fathom_id, title, meeting_date, call_type, summary,
                   action_items, attendees, transcript, share_url
            FROM meetings
            ORDER BY meeting_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_meeting_count(self) -> int:
        """Return the total number of indexed meetings."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM meetings").fetchone()
        return row["cnt"]

    def get_meeting_by_id(self, fathom_id: str) -> Optional[dict]:
        """Get a full meeting by its Fathom ID, including transcript."""
        row = self.conn.execute(
            """
            SELECT fathom_id, title, meeting_date, call_type, summary,
                   action_items, attendees, transcript, share_url
            FROM meetings
            WHERE fathom_id = ?
            """,
            (fathom_id,),
        ).fetchone()
        return dict(row) if row else None

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, date

from slack_sdk import WebClient

from src.config import load_config
from src.slack_bot.app import SlackBot
from src.indexer import MessageIndexer
from src.storage.database import get_connection, initialize_schema
from src.storage.models import MessageStore
from src.ai.client import AIClient

logger = logging.getLogger(__name__)

REINDEX_INTERVAL = 300  # 5 minutes
SUMMARY_INTERVAL = 86400  # 24 hours
GMAIL_POLL_INTERVAL = 60  # 1 minute
FATHOM_POLL_INTERVAL = 300  # 5 minutes


class Orchestrator:
    """Main coordination layer for CM Secure Assistant.

    Features:
    - Indexes channel history into SQLite
    - Answers questions via @mention, /ask, and DMs
    - Replies in threads to keep channels clean
    - Logs all questions for analytics
    - Tracks thumbs up/down feedback
    - Posts daily summaries to a dedicated channel
    """

    def __init__(self):
        self.config = load_config()

        # Storage
        conn = get_connection(self.config.db_path)
        initialize_schema(conn)
        self.message_store = MessageStore(conn)

        # Slack client for indexing
        self.slack_client = WebClient(token=self.config.slack_bot_token)

        # Message indexer
        self.indexer = MessageIndexer(self.slack_client, self.message_store)

        # Fathom (optional — only if API key is set)
        self.fathom_poller = None
        if self.config.fathom_api_key:
            try:
                from src.fathom.client import FathomClient
                from src.fathom.poller import FathomPoller
                fathom_client = FathomClient(self.config.fathom_api_key)
                self.fathom_poller = FathomPoller(fathom_client, self.message_store)
                logger.info("Fathom integration enabled")
            except Exception:
                logger.exception("Fathom integration failed to initialize")

        # Gmail (optional — only if credentials exist)
        self.gmail_poller = None
        try:
            from src.gmail.auth import get_gmail_credentials
            from src.gmail.poller import GmailPoller
            creds = get_gmail_credentials(
                self.config.gmail_credentials_path,
                self.config.gmail_token_path,
            )
            self.gmail_poller = GmailPoller(creds, self.message_store)
            logger.info("Gmail integration enabled for projects@casamkali.com")
        except Exception:
            logger.exception("Gmail integration failed to initialize")

        # AI
        self.ai_client = AIClient(self.config, self.message_store)

        # Slack bot (real-time events)
        self.slack_bot = SlackBot(
            self.config,
            on_channel_message=self.on_channel_message,
            on_question=self.on_question,
            on_feedback=self.on_feedback,
            on_dm=self.on_dm,
            on_digest_command=self.on_digest_command,
            on_thread_update=self.on_thread_update,
            on_client_reports=self.on_client_reports,
            on_followup=self.on_followup,
        )

        self._running = False

        # Conversation history: keyed by thread_ts (channels) or channel_id (DMs).
        # Each value is {"messages": [{"role": ..., "content": ...}], "ts": float}.
        # Capped at 50 conversations; oldest evicted when full.
        self._conversations: OrderedDict[str, dict] = OrderedDict()
        self._conv_lock = threading.Lock()
        self._conv_max = 50
        self._conv_ttl = 3600  # 1 hour

    # --- Conversation history helpers ---

    def _get_conversation(self, conv_key: str) -> list[dict]:
        """Return conversation history for a key, or empty list if expired/missing."""
        with self._conv_lock:
            entry = self._conversations.get(conv_key)
            if not entry:
                return []
            if time.time() - entry["ts"] > self._conv_ttl:
                self._conversations.pop(conv_key, None)
                return []
            return list(entry["messages"])

    def _append_conversation(self, conv_key: str, role: str, content: str):
        """Append a message to a conversation, creating it if needed."""
        with self._conv_lock:
            if conv_key not in self._conversations:
                # Evict oldest if at capacity
                while len(self._conversations) >= self._conv_max:
                    self._conversations.popitem(last=False)
                self._conversations[conv_key] = {"messages": [], "ts": time.time()}
            entry = self._conversations[conv_key]
            entry["messages"].append({"role": role, "content": content})
            entry["ts"] = time.time()
            # Keep last 10 turns (5 exchanges) to stay within token limits
            if len(entry["messages"]) > 10:
                entry["messages"] = entry["messages"][-10:]

    def on_channel_message(
        self, channel_id, channel_name, user_id, user_name, text, ts, thread_ts
    ):
        """Called when a new channel message arrives — store it immediately."""
        self.message_store.store_message(
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
            user_name=user_name,
            text=text,
            ts=ts,
            thread_ts=thread_ts,
        )

    def on_question(self, user_id, text, channel_id, say, source="mention", thread_ts=None):
        """Called when a team member asks a question."""
        logger.info("Question from %s via %s: %s", user_id, source, text[:80])

        # Log the question
        question_id = self.message_store.log_question(
            user_id=user_id,
            question=text,
            source=source,
            channel_id=channel_id,
        )

        # Use thread_ts as conversation key for channel threads
        conv_key = thread_ts if thread_ts else None

        try:
            history = self._get_conversation(conv_key) if conv_key else None
            answer = self.ai_client.answer_question(text, conversation_history=history)
            resp = say(answer)

            # Track conversation history
            if conv_key:
                self._append_conversation(conv_key, "user", text)
                self._append_conversation(conv_key, "assistant", answer)

            # Track the answer's message ts for feedback linking
            if resp and isinstance(resp, dict):
                answer_ts = resp.get("ts")
                if answer_ts:
                    self.message_store.set_answer_ts(question_id, answer_ts)
                    # Add thumbs up/down reactions for feedback
                    self.slack_bot.add_reactions(channel_id, answer_ts)

        except Exception:
            logger.exception("Error answering question from %s", user_id)
            say(
                "Sorry, I ran into an error while searching. "
                "Please try again or rephrase your question."
            )

    def on_followup(self, user_id, text, channel_id, thread_ts, say):
        """Called when a user replies in a thread under a bot answer — continue the conversation."""
        logger.info("Follow-up from %s in thread %s: %s", user_id, thread_ts, text[:80])

        self.message_store.log_question(
            user_id=user_id,
            question=text,
            source="followup",
            channel_id=channel_id,
        )

        try:
            history = self._get_conversation(thread_ts)
            answer = self.ai_client.answer_question(text, conversation_history=history)
            resp = say(answer)

            self._append_conversation(thread_ts, "user", text)
            self._append_conversation(thread_ts, "assistant", answer)

            if resp and isinstance(resp, dict):
                answer_ts = resp.get("ts")
                if answer_ts:
                    self.slack_bot.add_reactions(channel_id, answer_ts)

        except Exception:
            logger.exception("Error answering follow-up from %s", user_id)
            say("Sorry, I ran into an error. Please try again.")

    # Trigger phrases that map to the digest handler
    DIGEST_TRIGGERS = {"update me", "what did i miss", "catch me up", "digest", "hi", "hey", "hello"}

    def _is_digest_request(self, text: str) -> bool:
        """Check if the message is a digest trigger phrase."""
        text_lower = text.lower().strip().rstrip("!.?")
        return text_lower in self.DIGEST_TRIGGERS

    def on_dm(self, user_id, text, channel_id, say, client):
        """Called when a user DMs the bot.

        Digest triggers: "update me", "what did i miss", "catch me up", "digest"
        Everything else is treated as a question.
        """
        # Strip bot @mention if present (users sometimes @mention in DMs)
        clean_text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
        if not clean_text:
            clean_text = text

        # Log the interaction
        self.message_store.log_question(
            user_id=user_id,
            question=clean_text,
            source="dm",
            channel_id=channel_id,
        )

        # Check if it's a digest trigger
        if not self._is_digest_request(clean_text):
            # Treat as a question — use channel_id as conversation key for DMs
            say("Searching through team conversations... one moment.")
            try:
                history = self._get_conversation(channel_id)
                answer = self.ai_client.answer_question(clean_text, conversation_history=history)
                say(answer)
                self._append_conversation(channel_id, "user", clean_text)
                self._append_conversation(channel_id, "assistant", answer)
            except Exception:
                logger.exception("Error answering DM question from %s", user_id)
                say("Sorry, I ran into an error. Please try again.")
            return

        # Generate personalized digest
        self._send_digest(user_id=user_id, say=say, client=client)

    def on_digest_command(self, user_id, channel_id, say, client):
        """Called when /updateme slash command is used."""
        self.message_store.log_question(
            user_id=user_id,
            question="/updateme",
            source="slash",
            channel_id=channel_id,
        )
        self._send_digest(user_id=user_id, say=say, client=client)

    def _send_digest(self, user_id, say, client):
        """Generate and send a personalized digest to the user."""
        say("Building your personalized digest... one moment.")

        try:
            # Get channels the user is a member of
            user_channels = []
            cursor = None
            while True:
                resp = client.users_conversations(
                    user=user_id,
                    types="public_channel,private_channel",
                    exclude_archived=True,
                    limit=200,
                    cursor=cursor,
                )
                user_channels.extend(resp["channels"])
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

            channel_ids = [ch["id"] for ch in user_channels]
            channel_names = [ch["name"] for ch in user_channels]

            # Get full user profile
            user_profile = {}
            try:
                user_info = client.users_info(user=user_id)
                profile = user_info["user"]["profile"]
                user_name = profile.get("display_name") or profile.get("real_name") or user_id
                user_profile = {
                    "display_name": profile.get("display_name", ""),
                    "real_name": profile.get("real_name", ""),
                    "title": profile.get("title", ""),
                    "status_text": profile.get("status_text", ""),
                    "status_emoji": profile.get("status_emoji", ""),
                    "tz": user_info["user"].get("tz", ""),
                }
            except Exception:
                user_name = user_id

            logger.info("Generating digest for %s across %d channels", user_name, len(channel_ids))

            digest = self.ai_client.generate_personal_digest(
                user_id=user_id,
                user_name=user_name,
                channel_ids=channel_ids,
                channel_names=channel_names,
                user_profile=user_profile,
            )
            say(digest)

        except Exception:
            logger.exception("Error generating digest for %s", user_id)
            say("Sorry, I couldn't generate your digest. Try asking a specific question instead.")

    def on_thread_update(self, user_id, user_name, text, channel_id, thread_ts, say):
        """Called when a user replies in a thread under a bot message with an update."""
        logger.info("Team update from %s: %s", user_name, text[:80])

        update_id = self.message_store.save_team_update(
            user_id=user_id,
            user_name=user_name,
            update_text=text,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )

        say(f"Got it, saved your update. This will be included in future digests.")
        logger.info("Saved team update #%d from %s", update_id, user_name)

    def on_feedback(self, answer_ts, feedback):
        """Called when a user reacts with thumbs up/down on a bot answer."""
        question = self.message_store.get_question_by_answer_ts(answer_ts)
        if question:
            self.message_store.set_question_feedback(question["id"], feedback)
            logger.info(
                "Feedback recorded: %s for question #%d: %s",
                feedback, question["id"], question["question"][:50],
            )

    def _post_daily_summary(self):
        """Post a summary of question activity to the dedicated channel."""
        if not self.config.slack_summary_channel_id:
            return

        stats = self.message_store.get_question_stats()
        top_questions = self.message_store.get_top_questions(limit=10)

        total = stats["total_questions"]
        if total == 0:
            return

        up = stats["total_thumbs_up"] or 0
        down = stats["total_thumbs_down"] or 0
        users = stats["unique_users"]

        lines = [
            "*CM Secure Assistant — Weekly Summary*\n",
            f"*Total questions:* {total}",
            f"*Unique users:* {users}",
            f"*Feedback:* {up} :thumbsup:  {down} :thumbsdown:\n",
        ]

        if top_questions:
            lines.append("*Most asked topics:*")
            for i, q in enumerate(top_questions[:10], 1):
                count = q["ask_count"]
                question_text = q["question"][:60]
                lines.append(f"{i}. _{question_text}_ ({count}x)")

        # Find questions with thumbs down — knowledge gaps
        gaps = [q for q in top_questions if (q["thumbs_down"] or 0) > 0]
        if gaps:
            lines.append("\n*Knowledge gaps (questions with :thumbsdown:):*")
            for q in gaps[:5]:
                lines.append(f"• _{q['question'][:60]}_")

        summary_text = "\n".join(lines)

        try:
            self.slack_bot.post_message(
                self.config.slack_summary_channel_id,
                summary_text,
            )
            logger.info("Posted weekly summary to summary channel")
        except Exception:
            logger.exception("Error posting summary")

    def _reindex_loop(self):
        """Background thread: periodically re-indexes all channels."""
        while self._running:
            time.sleep(REINDEX_INTERVAL)
            try:
                logger.info("Starting periodic re-index...")
                self.indexer.index_all_channels()
                total = self.message_store.get_message_count()
                logger.info("Re-index complete. Total messages indexed: %d", total)
            except Exception:
                logger.exception("Error during periodic re-index")

    def _summary_loop(self):
        """Background thread: posts periodic summaries."""
        if not self.config.slack_summary_channel_id:
            logger.info("No summary channel configured, skipping summary loop")
            return

        while self._running:
            time.sleep(SUMMARY_INTERVAL)
            try:
                self._post_daily_summary()
            except Exception:
                logger.exception("Error in summary loop")

    def on_client_reports(self, user_id, channel_id, say, client):
        """Called when someone requests client status reports via /clientreports or @mention."""
        self.message_store.log_question(
            user_id=user_id,
            question="/clientreports",
            source="slash",
            channel_id=channel_id,
        )

        say("Processing weekly client status reports... this may take a moment.")

        try:
            reports = self.ai_client.process_weekly_status_reports()
            if not reports:
                say("No weekly status report emails found. Make sure they're in the projects@casamkali.com inbox with subject format: _Weekly Status Report - ClientName - Date_")
                return

            for report in reports:
                say(report["summary"])

            logger.info("Posted %d client reports for %s", len(reports), user_id)

        except Exception:
            logger.exception("Error processing client reports for %s", user_id)
            say("Sorry, I ran into an error processing the reports. Please try again.")

    def _gmail_poll_loop(self):
        """Background thread: polls Gmail for new emails."""
        if not self.gmail_poller:
            return

        # Initial fetch — get all inbox emails (up to 200)
        try:
            logger.info("Starting initial email fetch from projects@casamkali.com...")
            initial_emails = self.gmail_poller.poll_new_messages(
                max_results=200, query="in:anywhere"
            )
            logger.info("Gmail returned %d emails to process", len(initial_emails))
            stored = 0
            for email in initial_emails:
                logger.info("Storing email: %s", email.get("subject", "no subject")[:60])
                if self.message_store.store_email(
                    gmail_id=email["id"],
                    from_addr=email["from"],
                    to_addr=email["to"],
                    subject=email["subject"],
                    body=email["body"],
                    snippet=email["snippet"],
                    email_date=email["date"],
                ):
                    stored += 1
            logger.info("Initial email fetch complete: %d new emails indexed", stored)
        except Exception as e:
            logger.exception("Error during initial email fetch: %s", str(e))

        # Ongoing polling
        while self._running:
            time.sleep(GMAIL_POLL_INTERVAL)
            try:
                new_emails = self.gmail_poller.poll_new_messages(
                    max_results=20, query="is:inbox newer_than:1d"
                )
                stored = 0
                for email in new_emails:
                    if self.message_store.store_email(
                        gmail_id=email["id"],
                        from_addr=email["from"],
                        to_addr=email["to"],
                        subject=email["subject"],
                        body=email["body"],
                        snippet=email["snippet"],
                        email_date=email["date"],
                    ):
                        stored += 1
                if stored:
                    logger.info("Indexed %d new emails", stored)
            except Exception:
                logger.exception("Error polling Gmail")

    def _fathom_poll_loop(self):
        """Background thread: polls Fathom for new meetings."""
        if not self.fathom_poller:
            return

        # Initial fetch
        try:
            logger.info("Starting initial Fathom meeting sync...")
            stored = self.fathom_poller.poll_and_store()
            total = self.message_store.get_meeting_count()
            logger.info("Initial Fathom sync complete: %d new meetings. Total: %d", stored, total)
        except Exception:
            logger.exception("Error during initial Fathom sync")

        # Ongoing polling
        while self._running:
            time.sleep(FATHOM_POLL_INTERVAL)
            try:
                stored = self.fathom_poller.poll_and_store()
                if stored:
                    logger.info("Fathom poll: indexed %d new meetings", stored)
            except Exception:
                logger.exception("Error polling Fathom")

    def _initial_index(self):
        """Background thread: initial Slack message backfill."""
        logger.info("Starting initial message indexing...")
        try:
            total_new = self.indexer.index_all_channels()
            total = self.message_store.get_message_count()
            logger.info(
                "Initial indexing complete: %d new messages. Total: %d",
                total_new, total,
            )
        except Exception:
            logger.exception("Error during initial indexing")

    def run(self):
        """Start the CM Secure Assistant."""
        self._running = True

        # Start initial Slack indexing in background (non-blocking)
        index_thread = threading.Thread(
            target=self._initial_index, daemon=True, name="initial-index",
        )
        index_thread.start()

        # Start Gmail polling immediately (don't wait for Slack indexing)
        if self.gmail_poller:
            gmail_thread = threading.Thread(
                target=self._gmail_poll_loop, daemon=True, name="gmail-poller",
            )
            gmail_thread.start()
            logger.info("Gmail polling started (every %ds)", GMAIL_POLL_INTERVAL)

        # Start Fathom polling
        if self.fathom_poller:
            fathom_thread = threading.Thread(
                target=self._fathom_poll_loop, daemon=True, name="fathom-poller",
            )
            fathom_thread.start()
            logger.info("Fathom polling started (every %ds)", FATHOM_POLL_INTERVAL)

        # Start periodic re-indexing
        reindex_thread = threading.Thread(
            target=self._reindex_loop, daemon=True, name="reindex-loop",
        )
        reindex_thread.start()

        # Start summary posting
        summary_thread = threading.Thread(
            target=self._summary_loop, daemon=True, name="summary-loop",
        )
        summary_thread.start()

        # Start Slack bot (blocking)
        logger.info("Starting CM Secure Assistant (Socket Mode)...")
        logger.info("Team members can use @mention, /ask, or /clientreports!")
        try:
            self.slack_bot.start()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self._running = False

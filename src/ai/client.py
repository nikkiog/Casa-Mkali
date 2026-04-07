from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from anthropic import Anthropic

from src.ai.prompts import SYSTEM_PROMPT, DIGEST_PROMPT, CLIENT_REPORT_PROMPT
from src.storage.models import MessageStore

logger = logging.getLogger(__name__)


class AIClient:
    """Answers team questions by searching indexed Slack messages and using Claude."""

    def __init__(self, config, message_store: MessageStore):
        self.client = Anthropic(api_key=config.anthropic_api_key)
        self.model = "claude-sonnet-4-20250514"
        self.message_store = message_store

    def answer_question(self, question: str) -> str:
        """Search messages, emails, and meetings to answer a team member's question."""
        message_results, email_results = self._search_for_context(question)
        meeting_results = self._search_meetings_for_context(question)

        if not message_results and not email_results and not meeting_results:
            return (
                "I couldn't find any relevant messages, emails, or meeting notes matching your question. "
                "Try rephrasing with different keywords, or ask about a specific "
                "channel or person."
            )

        context_parts = []
        if message_results:
            context_parts.append("SLACK MESSAGES:")
            context_parts.append(self._format_messages_as_context(message_results))
        if email_results:
            context_parts.append("EMAILS (projects@casamkali.com):")
            context_parts.append(self._format_emails_as_context(email_results))
        if meeting_results:
            context_parts.append("MEETING NOTES & TRANSCRIPTS (from Fathom):")
            context_parts.append(self._format_meetings_as_context(meeting_results))

        context = "\n\n".join(context_parts)

        user_prompt = (
            f"A team member is asking: \"{question}\"\n\n"
            f"Here are the relevant messages and emails I found:\n\n"
            f"{context}\n\n"
            f"Based on these, answer the team member's question. "
            f"Only use information from the messages and emails above."
        )

        logger.info(
            "Answering question with %d messages, %d emails, %d meetings",
            len(message_results), len(email_results), len(meeting_results),
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return self._to_slack_formatting(response.content[0].text)

    @staticmethod
    def _to_slack_formatting(text: str) -> str:
        """Convert Markdown formatting to Slack mrkdwn formatting."""
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        text = re.sub(r"__(.+?)__", r"*\1*", text)
        return text

    def _search_for_context(self, question: str) -> list[dict]:
        """Run multiple search strategies to find relevant messages."""
        all_results = {}

        for msg in self.message_store.search_messages(question, limit=20):
            all_results[msg["ts"]] = msg

        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "what", "when",
            "where", "who", "how", "why", "do", "does", "did", "has", "have",
            "had", "will", "would", "could", "should", "can", "may", "might",
            "about", "with", "from", "this", "that", "they", "them", "their",
            "our", "we", "us", "it", "its", "any", "all", "been", "being",
            "for", "and", "but", "not", "you", "your", "of", "in", "on",
            "to", "at", "by",
        }
        words = [w for w in question.lower().split() if w not in stop_words and len(w) > 2]

        for word in words[:5]:
            for msg in self.message_store.search_messages(word, limit=10):
                all_results[msg["ts"]] = msg

        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i+1]}"
            for msg in self.message_store.search_messages(pair, limit=10):
                all_results[msg["ts"]] = msg

        results = sorted(all_results.values(), key=lambda m: m["ts"], reverse=True)

        # Search ALL emails by keyword (no time limit)
        email_results = {}
        for email in self.message_store.search_emails(question, limit=20):
            email_results[email["gmail_id"]] = email

        for word in words[:5]:
            for email in self.message_store.search_emails(word, limit=10):
                email_results[email["gmail_id"]] = email

        # For generic/broad questions, also include last 7 days of emails
        is_generic = len(words) <= 2
        if is_generic or not email_results:
            for email in self.message_store.get_recent_emails(hours=168, limit=20):
                email_results[email["gmail_id"]] = email

        email_list = sorted(
            email_results.values(),
            key=lambda e: e.get("email_date", ""),
            reverse=True,
        )

        return results[:50], email_list[:30]

    def generate_personal_digest(
        self,
        user_id: str,
        user_name: str,
        channel_ids: list[str],
        channel_names: list[str],
        user_profile: dict,
    ) -> str:
        """Generate a personalized digest for a user.

        Uses the dedicated DIGEST_PROMPT with the user's profile,
        channels, and recent activity.
        """
        # Get messages mentioning this user
        mentions = self.message_store.get_messages_mentioning_user(user_id, hours=24)

        # Get recent messages from their channels
        recent = self.message_store.get_recent_messages_for_channels(
            channel_ids, hours=24, limit=200,
        )

        # Get messages the user has sent (for style inference)
        user_messages = self.message_store.get_messages_by_user(user_id, hours=168, limit=30)

        # Get team updates submitted via thread replies
        team_updates = self.message_store.get_recent_updates(hours=24, limit=50)

        # Get recent emails
        recent_emails = self.message_store.get_recent_emails(hours=24, limit=20)

        # Get recent meetings
        recent_meetings = self.message_store.get_recent_meetings(limit=10)

        if not mentions and not recent and not team_updates and not recent_emails and not recent_meetings:
            return (
                "Nothing new in your channels, inbox, or meetings in the last 24 hours. "
                "You're all caught up!"
            )

        # Build context
        context_parts = []

        if mentions:
            context_parts.append("MESSAGES THAT @MENTION YOU:")
            context_parts.append(self._format_messages_as_context(mentions))

        if recent:
            context_parts.append("RECENT ACTIVITY IN YOUR CHANNELS:")
            context_parts.append(self._format_messages_as_context(recent))

        if team_updates:
            context_parts.append("TEAM UPDATES (submitted by team members):")
            update_lines = []
            for u in team_updates:
                name = u.get("user_name") or u.get("user_id", "unknown")
                update_lines.append(f"[{u['created_at']}] {name}: {u['update_text']}")
            context_parts.append("\n\n".join(update_lines))

        if recent_emails:
            context_parts.append("RECENT EMAILS (projects@casamkali.com):")
            context_parts.append(self._format_emails_as_context(recent_emails))

        if recent_meetings:
            context_parts.append("RECENT MEETINGS (from Fathom):")
            context_parts.append(self._format_meetings_as_context(recent_meetings))

        if user_messages:
            context_parts.append("YOUR RECENT MESSAGES (for style reference):")
            context_parts.append(self._format_messages_as_context(user_messages))

        context = "\n\n".join(context_parts)

        # Build the personalized system prompt
        channel_list = ", ".join(f"#{name}" for name in channel_names)
        profile_json = json.dumps(user_profile, indent=2, default=str)

        system = DIGEST_PROMPT.format(
            display_name=user_name,
            channel_list=channel_list,
            user_profile_json=profile_json,
        )

        user_prompt = (
            f"Here are the messages from the last 24 hours:\n\n"
            f"{context}\n\n"
            f"Generate my personalized digest with suggested responses."
        )

        logger.info(
            "Generating digest for %s with %d mentions, %d recent, %d own messages",
            user_name, len(mentions), len(recent), len(user_messages),
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return self._to_slack_formatting(response.content[0].text)

    def _format_messages_as_context(self, messages: list[dict]) -> str:
        """Format messages into readable context for Claude."""
        lines = []
        for msg in messages:
            ts_float = float(msg["ts"])
            dt = datetime.fromtimestamp(ts_float)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            user = msg.get("user_name") or msg.get("user_id", "unknown")
            channel = msg.get("channel_name", "unknown")
            text = msg["text"]
            lines.append(f"[{date_str}] #{channel} — {user}: {text}")
        return "\n\n".join(lines)

    def _format_emails_as_context(self, emails: list[dict]) -> str:
        """Format emails into readable context for Claude."""
        lines = []
        for email in emails:
            date = email.get("email_date", "unknown date")
            sender = email.get("from_addr", "unknown")
            subject = email.get("subject", "(no subject)")
            snippet = email.get("snippet", "")
            lines.append(f"[{date}] From: {sender}\nSubject: {subject}\n{snippet}")
        return "\n\n".join(lines)

    def _search_meetings_for_context(self, question: str) -> list[dict]:
        """Search meetings by keyword, similar to message/email search."""
        all_results = {}

        for mtg in self.message_store.search_meetings(question, limit=10):
            all_results[mtg["fathom_id"]] = mtg

        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "what", "when",
            "where", "who", "how", "why", "do", "does", "did", "has", "have",
            "had", "will", "would", "could", "should", "can", "may", "might",
            "about", "with", "from", "this", "that", "they", "them", "their",
            "our", "we", "us", "it", "its", "any", "all", "been", "being",
            "for", "and", "but", "not", "you", "your", "of", "in", "on",
            "to", "at", "by",
        }
        words = [w for w in question.lower().split() if w not in stop_words and len(w) > 2]

        for word in words[:5]:
            for mtg in self.message_store.search_meetings(word, limit=5):
                all_results[mtg["fathom_id"]] = mtg

        # For broad questions, also include recent meetings
        if len(words) <= 2 or not all_results:
            for mtg in self.message_store.get_recent_meetings(limit=10):
                all_results[mtg["fathom_id"]] = mtg

        results = sorted(
            all_results.values(),
            key=lambda m: m.get("meeting_date") or "",
            reverse=True,
        )
        return results[:20]

    def _format_meetings_as_context(self, meetings: list[dict]) -> str:
        """Format meetings into readable context for Claude."""
        lines = []
        for mtg in meetings:
            date = mtg.get("meeting_date", "unknown date")
            title = mtg.get("title", "Untitled Meeting")
            call_type = mtg.get("call_type", "")
            attendees = mtg.get("attendees", "")
            summary = mtg.get("summary", "")
            action_items = mtg.get("action_items", "")
            share_url = mtg.get("share_url", "")

            parts = [f"[{date}] Meeting: {title}"]
            if call_type:
                parts.append(f"Type: {call_type}")
            if attendees:
                parts.append(f"Attendees: {attendees}")
            if summary:
                parts.append(f"Summary: {summary}")
            if action_items:
                parts.append(f"Action Items:\n{action_items}")
            if share_url:
                parts.append(f"Recording: {share_url}")

            lines.append("\n".join(parts))
        return "\n\n---\n\n".join(lines)

    def process_weekly_status_reports(self) -> list[dict]:
        """Find and process weekly status report emails.

        Searches for emails with subject matching
        "Weekly Status Report - {client} - {date}" and generates
        a client intelligence summary for each.

        Returns a list of dicts with client_name and summary.
        """
        # Search for status report emails from the last 7 days
        report_emails = self.message_store.search_emails(
            "Weekly Status Report", limit=50,
        )

        if not report_emails:
            return []

        results = []
        # Get last week's reports for comparison
        previous_reports = self.message_store.search_emails(
            "Weekly Status Report", limit=100,
        )

        for email in report_emails:
            subject = email.get("subject", "")

            # Extract client name from subject
            # Expected format: "Weekly Status Report - ClientName - Date"
            parts = subject.split(" - ")
            if len(parts) >= 2:
                client_name = parts[1].strip()
            else:
                client_name = "Unknown Client"

            # Get the full email body
            full_email = self.message_store.get_email_by_id(email.get("gmail_id", ""))
            body = full_email.get("body", email.get("snippet", "")) if full_email else email.get("snippet", "")

            # Find previous reports for this client
            prev_reports = [
                e for e in previous_reports
                if client_name.lower() in e.get("subject", "").lower()
                and e.get("gmail_id") != email.get("gmail_id")
            ]

            prev_context = ""
            if prev_reports:
                prev = prev_reports[0]
                prev_full = self.message_store.get_email_by_id(prev.get("gmail_id", ""))
                prev_body = prev_full.get("body", prev.get("snippet", "")) if prev_full else prev.get("snippet", "")
                prev_context = (
                    f"\n\nPREVIOUS WEEK'S REPORT FOR COMPARISON:\n"
                    f"Subject: {prev.get('subject', '')}\n"
                    f"{prev_body[:3000]}"
                )

            system = CLIENT_REPORT_PROMPT.format(client_name=client_name)

            user_prompt = (
                f"Here is this week's status report:\n\n"
                f"Subject: {subject}\n"
                f"From: {email.get('from_addr', 'unknown')}\n"
                f"Date: {email.get('email_date', 'unknown')}\n\n"
                f"{body[:5000]}"
                f"{prev_context}\n\n"
                f"Process this report."
            )

            logger.info("Processing status report for client: %s", client_name)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )

            summary = self._to_slack_formatting(response.content[0].text)
            results.append({
                "client_name": client_name,
                "summary": summary,
                "email_date": email.get("email_date", ""),
            })

        return results

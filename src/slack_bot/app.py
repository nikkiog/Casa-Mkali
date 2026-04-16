from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logger = logging.getLogger(__name__)


class SlackBot:
    """CM Secure Assistant Slack bot.

    Features:
    - Replies in threads to keep channels clean
    - Supports @mentions and /ask slash command
    - Adds thumbs up/down reactions for feedback
    - Indexes channel messages for search
    """

    def __init__(
        self,
        config,
        on_channel_message: Callable,
        on_question: Callable,
        on_feedback: Callable,
        on_dm: Callable,
        on_digest_command: Callable,
        on_thread_update: Callable,
        on_client_reports: Callable,
        on_followup: Callable,
    ):
        self.config = config
        self.on_channel_message = on_channel_message
        self.on_question = on_question
        self.on_feedback = on_feedback
        self.on_dm = on_dm
        self.on_digest_command = on_digest_command
        self.on_thread_update = on_thread_update
        self.on_client_reports = on_client_reports
        self.on_followup = on_followup
        self.app = App(token=config.slack_bot_token)
        self._bot_user_id: Optional[str] = None
        self._handler: Optional[SocketModeHandler] = None
        self._register_listeners()

    def _get_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            resp = self.app.client.auth_test()
            self._bot_user_id = resp["user_id"]
        return self._bot_user_id

    def _strip_mention(self, text: str) -> str:
        bot_id = self._get_bot_user_id()
        return re.sub(rf"<@{bot_id}>\s*", "", text).strip()

    def _register_listeners(self):
        # --- /ask slash command ---
        @self.app.command("/ask")
        def handle_ask_command(ack, command, client):
            ack()
            user_id = command["user_id"]
            text = command.get("text", "").strip()
            channel_id = command["channel_id"]

            if not text:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Usage: /ask <your question>\nExample: /ask what did we decide about the schedule?",
                )
                return

            logger.info("/ask command from %s: %s", user_id, text[:80])

            # Post the question visibly in the channel
            question_msg = client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> asked: _{text}_",
            )
            question_ts = question_msg["ts"]

            # Answer in a thread
            def say_in_thread(response_text):
                resp = client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=question_ts,
                    text=response_text,
                )
                return resp

            # Send thinking message in thread
            say_in_thread("Searching through team conversations... one moment.")

            self.on_question(
                user_id=user_id,
                text=text,
                channel_id=channel_id,
                say=say_in_thread,
                source="slash",
                thread_ts=question_ts,
            )

        # --- /updateme slash command ---
        @self.app.command("/updateme")
        def handle_updateme_command(ack, command, client):
            ack()
            user_id = command["user_id"]
            channel_id = command["channel_id"]

            logger.info("/updateme command from %s", user_id)

            # Post visible message
            msg = client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> requested a personal digest",
            )
            msg_ts = msg["ts"]

            def say_in_thread(response_text):
                resp = client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=msg_ts,
                    text=response_text,
                )
                return resp

            self.on_digest_command(
                user_id=user_id,
                channel_id=channel_id,
                say=say_in_thread,
                client=client,
            )

        # --- /clientreports slash command ---
        @self.app.command("/clientreports")
        def handle_clientreports_command(ack, command, client):
            ack()
            user_id = command["user_id"]
            channel_id = command["channel_id"]

            logger.info("/clientreports command from %s", user_id)

            msg = client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> requested client status reports",
            )
            msg_ts = msg["ts"]

            def say_in_thread(response_text):
                resp = client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=msg_ts,
                    text=response_text,
                )
                return resp

            self.on_client_reports(
                user_id=user_id,
                channel_id=channel_id,
                say=say_in_thread,
                client=client,
            )

        # --- @mention handler ---
        @self.app.event("app_mention")
        def handle_mention(event, say, client):
            user_id = event.get("user", "unknown")
            text = event.get("text", "")
            channel_id = event["channel"]
            ts = event["ts"]

            question = self._strip_mention(text)

            # Reply in thread under the @mention
            def say_in_thread(response_text):
                resp = client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=ts,
                    text=response_text,
                )
                return resp

            if not question:
                say_in_thread("Hi! Ask me a question or say *catch me up* for a personal digest.\nYou can also use `/ask` or `/updateme`.")
                return

            # Check if it's a client reports trigger
            report_triggers = {"client reports", "clientreports", "status reports", "weekly reports"}
            if question.lower().strip().rstrip("!.?") in report_triggers:
                logger.info("@mention client reports request from %s", user_id)
                self.on_client_reports(
                    user_id=user_id,
                    channel_id=channel_id,
                    say=say_in_thread,
                    client=client,
                )
                return

            # Check if it's a digest trigger
            digest_triggers = {"update me", "what did i miss", "catch me up", "digest"}
            if question.lower().strip().rstrip("!.?") in digest_triggers:
                logger.info("@mention digest request from %s", user_id)
                self.on_digest_command(
                    user_id=user_id,
                    channel_id=channel_id,
                    say=say_in_thread,
                    client=client,
                )
                return

            logger.info("@mention question from %s: %s", user_id, question[:80])

            say_in_thread("Searching through team conversations... one moment.")

            self.on_question(
                user_id=user_id,
                text=question,
                channel_id=channel_id,
                say=say_in_thread,
                source="mention",
                thread_ts=ts,
            )

        # --- Channel message indexing + DM handling ---
        @self.app.event("message")
        def handle_message(event, say, client):
            channel_type = event.get("channel_type")
            subtype = event.get("subtype")
            if subtype is not None:
                return
            if event.get("bot_id"):
                return

            user_id = event.get("user", "unknown")
            text = event.get("text", "")
            ts = event["ts"]

            # DM — personalized digest or question
            if channel_type == "im":
                logger.info("DM from %s: %s", user_id, text[:80])
                self.on_dm(
                    user_id=user_id,
                    text=text,
                    channel_id=event["channel"],
                    say=say,
                    client=client,
                )
                return

            # Channel/group — index it
            if channel_type in ("channel", "group"):
                channel_id = event["channel"]
                thread_ts = event.get("thread_ts")

                try:
                    info = client.conversations_info(channel=channel_id)
                    channel_name = info["channel"]["name"]
                except Exception:
                    channel_name = channel_id

                try:
                    user_info = client.users_info(user=user_id)
                    profile = user_info["user"]["profile"]
                    user_name = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or user_id
                    )
                except Exception:
                    user_name = user_id

                # Check if this is a thread reply to a bot message
                if thread_ts and thread_ts != ts:
                    try:
                        parent = client.conversations_history(
                            channel=channel_id,
                            latest=thread_ts,
                            inclusive=True,
                            limit=1,
                        )
                        parent_msgs = parent.get("messages", [])
                        if parent_msgs:
                            parent_msg = parent_msgs[0]
                            bot_id = self._get_bot_user_id()
                            if parent_msg.get("user") == bot_id or parent_msg.get("bot_id"):
                                # Reply to the bot — treat as a follow-up question
                                logger.info(
                                    "Follow-up from %s in thread %s: %s",
                                    user_name, thread_ts, text[:80],
                                )

                                def say_in_thread(response_text):
                                    return client.chat_postMessage(
                                        channel=channel_id,
                                        thread_ts=thread_ts,
                                        text=response_text,
                                    )

                                self.on_followup(
                                    user_id=user_id,
                                    text=text,
                                    channel_id=channel_id,
                                    thread_ts=thread_ts,
                                    say=say_in_thread,
                                )
                                # Still index the message
                    except Exception:
                        logger.debug("Could not check parent message")

                logger.info(
                    "Channel message from %s in #%s: %s",
                    user_name, channel_name, text[:80],
                )

                self.on_channel_message(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    user_id=user_id,
                    user_name=user_name,
                    text=text,
                    ts=ts,
                    thread_ts=thread_ts,
                )

        # --- Reaction handler for thumbs up/down feedback ---
        @self.app.event("reaction_added")
        def handle_reaction(event, client):
            reaction = event.get("reaction", "")
            if reaction not in ("+1", "-1", "thumbsup", "thumbsdown"):
                return

            # Only track reactions on bot messages
            item = event.get("item", {})
            item_ts = item.get("ts")
            item_channel = item.get("channel")
            if not item_ts or not item_channel:
                return

            # Check if the reacted message is from our bot
            try:
                result = client.conversations_history(
                    channel=item_channel,
                    latest=item_ts,
                    inclusive=True,
                    limit=1,
                )
                messages = result.get("messages", [])
                if not messages:
                    return

                msg = messages[0]
                bot_id = self._get_bot_user_id()
                if msg.get("user") != bot_id and msg.get("bot_id") is None:
                    return
            except Exception:
                return

            feedback = "up" if reaction in ("+1", "thumbsup") else "down"
            user_id = event.get("user", "unknown")

            logger.info("Feedback %s from %s on message %s", feedback, user_id, item_ts)
            self.on_feedback(answer_ts=item_ts, feedback=feedback)

    def post_message(self, channel_id: str, text: str, thread_ts=None, blocks=None):
        """Post a message to a Slack channel, optionally in a thread."""
        self.app.client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
            blocks=blocks,
        )

    def add_reactions(self, channel_id: str, ts: str):
        """Add thumbs up/down reactions to a message for feedback."""
        try:
            self.app.client.reactions_add(channel=channel_id, name="thumbsup", timestamp=ts)
            self.app.client.reactions_add(channel=channel_id, name="thumbsdown", timestamp=ts)
        except Exception:
            logger.debug("Could not add feedback reactions")

    def start(self):
        self._handler = SocketModeHandler(self.app, self.config.slack_app_token)
        self._handler.start()

    def connect(self):
        self._handler = SocketModeHandler(self.app, self.config.slack_app_token)
        self._handler.connect()
        return self._handler

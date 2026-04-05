"""Message indexer — pulls history from all public/private channels."""
from __future__ import annotations

import logging
import time

from slack_sdk import WebClient

from src.storage.models import MessageStore

logger = logging.getLogger(__name__)


class MessageIndexer:
    """Fetches and stores Slack channel message history.

    Indexes messages from public and private channels only — never DMs.
    Supports incremental sync so it doesn't re-fetch already-indexed messages.
    """

    def __init__(self, client: WebClient, message_store: MessageStore):
        self.client = client
        self.store = message_store
        self._user_cache: dict[str, str] = {}

    def _resolve_user_name(self, user_id: str) -> str:
        """Look up a user's display name, with caching."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            resp = self.client.users_info(user=user_id)
            profile = resp["user"]["profile"]
            name = profile.get("display_name") or profile.get("real_name") or user_id
            self._user_cache[user_id] = name
            return name
        except Exception:
            self._user_cache[user_id] = user_id
            return user_id

    def get_channels(self) -> list[dict]:
        """List all public and private channels the bot is a member of."""
        channels = []
        cursor = None
        while True:
            resp = self.client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            channels.extend(resp["channels"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return channels

    def index_channel(self, channel_id: str, channel_name: str) -> int:
        """Index all messages from a single channel.

        Uses pagination and respects rate limits. Picks up where it left off
        if the channel was partially indexed before.

        Returns the number of new messages stored.
        """
        stored = 0
        cursor = None
        oldest = self.store.get_sync_state(channel_id) or "0"

        logger.info("Indexing #%s (oldest synced: %s)", channel_name, oldest)

        while True:
            try:
                resp = self.client.conversations_history(
                    channel=channel_id,
                    oldest=oldest,
                    limit=200,
                    cursor=cursor,
                )
            except Exception as e:
                if "ratelimited" in str(e).lower():
                    logger.warning("Rate limited, sleeping 5s...")
                    time.sleep(5)
                    continue
                logger.error("Error fetching history for #%s: %s", channel_name, e)
                break

            messages = resp.get("messages", [])
            for msg in messages:
                # Skip bot messages and subtypes (joins, leaves, etc.)
                if msg.get("bot_id") or msg.get("subtype"):
                    continue

                user_id = msg.get("user", "unknown")
                user_name = self._resolve_user_name(user_id)
                text = msg.get("text", "")
                ts = msg["ts"]
                thread_ts = msg.get("thread_ts")

                if text.strip():
                    self.store.store_message(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        user_id=user_id,
                        user_name=user_name,
                        text=text,
                        ts=ts,
                        thread_ts=thread_ts,
                    )
                    stored += 1

            # Track sync progress
            if messages:
                newest_ts = max(m["ts"] for m in messages)
                self.store.set_sync_state(channel_id, newest_ts)

            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor or not resp.get("has_more", False):
                break

            # Be polite to the Slack API
            time.sleep(1)

        logger.info("Indexed %d new messages from #%s", stored, channel_name)
        return stored

    def index_all_channels(self) -> int:
        """Index messages from all accessible channels.

        Returns total number of new messages stored.
        """
        channels = self.get_channels()
        logger.info("Found %d channels to index", len(channels))

        total = 0
        for ch in channels:
            count = self.index_channel(ch["id"], ch["name"])
            total += count

        logger.info("Indexing complete: %d new messages across %d channels", total, len(channels))
        return total

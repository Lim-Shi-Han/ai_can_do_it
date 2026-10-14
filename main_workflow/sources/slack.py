"""Slack source. One thread is one document, and access is live channel membership.

Reads only the channels the bot has been invited to, never DMs. Bot tokens cannot call
search.messages, so Slack candidates come from the index, which sync and the Slack bot's
events keep current.
"""

import hashlib
import os
import re
import textwrap
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from .base import Candidate, Doc

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
SGT = timezone(timedelta(hours=8))
THREAD_SUBTYPES = {None, "bot_message", "file_share"}   # the rest are joins, topic changes and the like
GONE = {"thread_not_found", "message_not_found", "channel_not_found", "not_in_channel"}
MENTION_RE = re.compile(r"<@(\w+)>")


def load_local_env():
    """Read SLACK_* settings from the repository's .env without executing it."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().startswith("SLACK_"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def thread_id(channel, message):
    """The document a message belongs to, or None for channel housekeeping such as joins."""
    root = message.get("thread_ts") or message["ts"]
    if root == message["ts"] and message.get("subtype") not in THREAD_SUBTYPES:
        return None
    return f"{channel}:{root}"


def _activity(message):
    """Latest post, reply, or edit in a thread, as seen on its root message."""
    return max(float(message["ts"]), float(message.get("latest_reply", 0)),
               float(message.get("edited", {}).get("ts", 0)))


def _sgt(ts):
    return datetime.fromtimestamp(float(ts), SGT).strftime("%Y-%m-%d %H:%M SGT")


def _iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SlackSource:
    name = "slack"

    def __init__(self):
        load_local_env()
        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            raise ValueError("Set SLACK_BOT_TOKEN in .env")
        self.api = WebClient(token=token)
        self.api.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=2))
        self._channel_names = {}
        self._people = {}
        self._synced = set()   # channels changes_since has already read in full

    @cached_property
    def _workspace_url(self):
        return self.api.auth_test()["url"].rstrip("/")

    def channel_name(self, channel):
        if channel not in self._channel_names:
            self._channel_names[channel] = self.api.conversations_info(channel=channel)["channel"]["name"]
        return self._channel_names[channel]

    def _person(self, user_id):
        if user_id not in self._people:
            user = self.api.users_info(user=user_id)["user"]
            self._people[user_id] = user.get("real_name") or user["name"]
        return self._people[user_id]

    def _line(self, message):
        author = self._person(message["user"]) if "user" in message else message.get("username", "bot")
        text = MENTION_RE.sub(lambda m: "@" + self._person(m.group(1)), message.get("text", ""))
        return f"{author} ({_sgt(message['ts'])}): {text}"

    def _channels(self):
        pages = self.api.users_conversations(types="public_channel,private_channel", exclude_archived=True, limit=200)
        for channel in (c for page in pages for c in page["channels"]):
            self._channel_names[channel["id"]] = channel["name"]
            yield channel["id"], channel["name"]

    def channel_members(self):
        """Slack user IDs in each channel the bot reads, for the platform console."""
        return {name: {m for page in self.api.conversations_members(channel=cid, limit=200) for m in page["members"]}
                for cid, name in self._channels()}

    def search(self, query, incident_id=None, limit=10):
        return []   # see the module docstring: the index supplies Slack candidates

    def can_access(self, user, doc_id):
        member = user.get("slack_user_id")
        if not member:
            return False
        pages = self.api.conversations_members(channel=doc_id.split(":", 1)[0], limit=200)
        return any(member in page["members"] for page in pages)

    def fetch(self, doc_id):
        channel, ts = doc_id.split(":", 1)
        try:
            pages = self.api.conversations_replies(channel=channel, ts=ts, limit=200)
            messages = list({m["ts"]: m for page in pages for m in page["messages"]}.values())
        except SlackApiError as exc:
            if exc.response["error"] in GONE:
                raise RuntimeError(f"Slack thread {doc_id}: {exc.response['error']}") from exc
            raise
        edits = [(m["ts"], m.get("edited", {}).get("ts", "")) for m in messages]
        name = self.channel_name(channel)
        return Doc(
            source=self.name,
            doc_id=doc_id,
            title=f"#{name}: " + textwrap.shorten(messages[0].get("text", ""), 60, placeholder="…"),
            url=f"{self._workspace_url}/archives/{channel}/p{ts.replace('.', '')}",
            version=hashlib.sha1(repr(edits).encode()).hexdigest()[:8],   # changes with any new, edited, or deleted message
            updated_at=_iso(max(float(edited or posted) for posted, edited in edits)),
            text="\n".join([f"#{name} thread started {_sgt(ts)}", *map(self._line, messages)]),
            container=name,
        )

    def changes_since(self, ts):
        since = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else 0
        found = {}
        for channel, name in self._channels():
            cutoff = since if channel in self._synced else 0   # a channel the bot has just joined is read in full
            for page in self.api.conversations_history(channel=channel, limit=200):
                for message in page["messages"]:
                    # a new reply does not move its thread up the history, so compare each thread's latest activity
                    doc_id = thread_id(channel, message)
                    if doc_id and _activity(message) > cutoff:
                        found[doc_id] = Candidate(self.name, doc_id, f"#{name}", name)
            self._synced.add(channel)
        return list(found.values())

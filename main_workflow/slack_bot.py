"""Slack front end: ask with /brain, and keep the Slack index current from Slack's own events.

Started by main_workflow.web over Socket Mode, so it needs no public URL. The app has no chat:write
scope. Answers go back only as the slash command's private reply, because an answer is scoped to
the asker's access and other people in the channel may have less.
"""

import os
import re
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from . import pipeline
from .audit import AuditLog
from .index import Index
from .memory import Memory
from .sources.slack import thread_id
from .sync import refresh

USAGE = "Ask `/brain <question>`, for example `/brain what is the status of INC-PAY-001?`. `/brain reset` clears your chat."
REMOVED = "_Earlier answers were removed from this chat: their sources changed or are no longer available to you._"
MEMORIES = {}
ASK_LOCK = threading.Lock()   # one question at a time, as the local model serves them anyway


def linked_user(slack_user_id):
    return next((name for name, u in pipeline.load_identities().items()
                 if u.get("slack_user_id") == slack_user_id), None)


def escape(text):
    """Slack escaping. Also stops source text from smuggling @channel pings or disguised links into a reply."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(doc):
    title = escape(doc.title)
    return f"<{doc.url}|{title}>" if doc.url.startswith("https://") else title


def to_mrkdwn(question, result):
    answer = re.sub(r"^#+\s*(.+)$", r"*\1*", escape(result.answer), flags=re.M)
    answer = re.sub(r"\*\*(.+?)\*\*", r"*\1*", answer)
    lines = [f">{escape(question)}", *([REMOVED] if result.dropped else []), answer]
    if result.cited:
        lines += ["*Sources*", *(f"[S{i}] {link(doc)} · {doc.source} v{doc.version}" for i, doc in result.cited)]
    return "\n\n".join(lines)


def start(sources, log):
    """Connect in the background. log(kind, text, ok=True) feeds the console's activity list."""
    slack, app_token = sources.get("slack"), os.environ.get("SLACK_APP_TOKEN")
    if slack is None or not app_token:
        log("slack", "Slack bot off: set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env", False)
        return
    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    @app.command("/brain")
    def ask(ack, command, respond):
        name, question = linked_user(command["user_id"]), command["text"].strip()
        if name is None:
            AuditLog().append(command["user_id"], "unknown_user", {"via": "slack"})
            return ack("Your Slack account is not linked to a Company A identity, so I can't answer.")
        if not question:
            return ack(USAGE)
        if question.lower() == "reset":
            MEMORIES.pop(name, None)
            return ack("Chat cleared.")
        ack("Checking only the sources you can access…")
        AuditLog().append(name, "sign_in", {"via": "slack", "slack_user_id": command["user_id"],
                                            "channel": command["channel_name"]})
        try:
            with ASK_LOCK:
                memory = MEMORIES.setdefault(name, Memory(name))
                result = pipeline.run(question, name, sources, AuditLog(), index=Index(), memory=memory)
        except Exception as exc:
            return respond(f"Sorry, I couldn't answer that ({type(exc).__name__}).", response_type="ephemeral")
        respond(to_mrkdwn(question, result), response_type="ephemeral")

    @app.event("message")
    def on_message(event):
        # new messages carry their own fields; edits and deletions wrap the message they changed
        doc_id = thread_id(event["channel"], event.get("message") or event.get("previous_message") or event)
        if doc_id is None:
            return
        updated, removed = refresh(Index(), slack, doc_id)
        if updated or removed:
            AuditLog().append("system", "sync", {"source": slack.name, "via": "slack_event",
                                                 "updated": updated, "removed": removed})
        for u in updated:
            log("sync", f"Slack event: {u['title']} v{u['version']}")
        for r in removed:
            log("sync", f"Slack event: removed {r}")

    @app.event(re.compile(r"^member_(joined|left)_channel$"))
    def on_membership(event):
        # access is checked live on every question; this only records when it changed
        name = linked_user(event["user"]) or event["user"]
        verb = "added to" if event["type"] == "member_joined_channel" else "removed from"
        change = f"{verb} #{slack.channel_name(event['channel'])}"
        AuditLog().append(name, "permission_change", {"via": "slack_event", "source": slack.name,
                                                      "slack_user_id": event["user"], "change": change})
        log("slack_access", f"Slack: {name} {change}")

    SocketModeHandler(app, app_token).connect()
    log("slack", "Slack bot connected: /brain is live")

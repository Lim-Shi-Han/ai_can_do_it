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

from . import actions, pipeline
from .audit import AuditLog
from .index import Index
from .memory import Memory
from .sources.slack import thread_id
from .sync import refresh

USAGE = "Ask `/brain <question>`, for example `/brain what is the status of INC-PAY-001?`. `/brain reset` clears your chat."
REMOVED = "_Earlier answers were removed from this chat: their sources changed or are no longer available to you._"
MEMORIES = {}
ASK_LOCK = threading.Lock()   # one question at a time, as the local model serves them anyway
REFRESH_LOCK = threading.Lock()   # a reply fires two events for one thread; refresh it once at a time


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


def button(action, label, value, **extra):
    return {"type": "button", "action_id": action, "value": value, "text": {"type": "plain_text", "text": label}, **extra}


def draft_blocks(question, draft):
    based_on = "\n".join(f"• {link(doc)}" for doc in draft.cited) or "No sources"
    details = "\n".join([
        f"*Draft {draft.project} ticket.* Nothing is created until you confirm; Jira assigns the number.",
        "",
        f"*Summary:* {escape(draft.summary)}",
        f"*Assignee:* {escape(draft.assignee or 'Unassigned')}",
        f"*Labels:* {escape(', '.join(draft.labels) or 'None')}",
        f"*Description:*\n{escape(draft.description)}",
        f"*Based on:*\n{based_on}",
    ])
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f">{escape(question)}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": details[:2900]}},   # Slack's limit is 3,000
        {"type": "actions", "elements": [button("brain_create", "Create in Jira", draft.id, style="primary"),
                                         button("brain_cancel", "Cancel", draft.id)]},
    ]


def reply_to(question, name, sources):
    """What /brain sends back: an answer, or a ticket draft the model proposed, for the user to confirm."""
    memory = MEMORIES.setdefault(name, Memory(name))
    result = pipeline.run(question, name, sources, AuditLog(), index=Index(), memory=memory, allow_actions=True)
    if result.draft:
        return {"text": f"Draft {result.draft.project} ticket: {escape(result.draft.summary)}",
                "blocks": draft_blocks(question, result.draft)}
    return {"text": to_mrkdwn(question, result)}


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
                reply = reply_to(question, name, sources)
        except Exception as exc:
            return respond(f"Sorry, I couldn't answer that ({type(exc).__name__}).", response_type="ephemeral")
        respond(response_type="ephemeral", **reply)

    @app.action(re.compile(r"^brain_(create|cancel)$"))
    def on_draft_decision(ack, body, action, respond):
        ack()
        name = linked_user(body["user"]["id"])
        try:
            created = actions.confirm(action["value"], name, action["action_id"] == "brain_create", sources,
                                      AuditLog(), pipeline.load_identities(), Index())
        except PermissionError as exc:   # expired, someone else's, or no longer allowed
            return respond(replace_original=True, text=escape(str(exc)))
        except Exception as exc:
            return respond(replace_original=True, text=f"Sorry, that failed ({type(exc).__name__}). Nothing was created.")
        if not created:
            return respond(replace_original=True, text="Cancelled. Nothing was created.")
        key, url = created
        log("action", f"{name} created {key} through the Brain")
        respond(replace_original=True, text=f"Created <{url}|{key}>.")

    @app.event("message")
    def on_message(event):
        # new messages carry their own fields; edits and deletions wrap the message they changed
        doc_id = thread_id(event["channel"], event.get("message") or event.get("previous_message") or event)
        if doc_id is None:
            return
        with REFRESH_LOCK:
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

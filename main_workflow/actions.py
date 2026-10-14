"""Actions the Brain takes for a user, starting with creating a Jira ticket.

Requests that ask for a ticket are offered the create_jira_ticket tool, and the model decides whether to call
it and with what. A call only produces a draft. The
asker sees the exact draft and confirms it; plain code then carries it out, and only if Jira itself
lets the asker create tickets in that project, checked live when drafting and again when confirming.
Drafts stay on the server, so what runs is exactly what was shown. Every step is audited.
"""

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from .sync import refresh

TOOL_NAME = "create_jira_ticket"
# Only requests like these are offered the tool: offered on every question, the model drafted tickets for
# plain questions about existing tickets, and its answers got worse.
REQUEST_RE = re.compile(r"\b(create|open|raise|file|log|make|add|submit)\b.{0,60}?\b(ticket|issue|jira|task|bug)\b",
                        re.IGNORECASE | re.DOTALL)
LABEL_RE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
TAG_RE = re.compile(r"S(\d+)")
ISSUE_TYPE = "Task"
DRAFT_TTL = 15 * 60   # seconds a draft can wait for confirmation

DRAFTS = {}
DRAFTS_LOCK = threading.Lock()


def asks_for_ticket(question):
    return bool(REQUEST_RE.search(question))


def ticket_tool(projects, people):
    return {"type": "function", "function": {
        "name": TOOL_NAME,
        "description": ("Propose a new Jira ticket for the user to review; nothing is created until they confirm. "
                        "Call this only when the user explicitly asks to create, open, raise, or log a new ticket. "
                        "Never call it to answer a question, even one that mentions an existing ticket. "
                        "Fill it only with facts from the numbered sources."),
        "parameters": {"type": "object", "required": ["project", "summary", "description", "sources"], "properties": {
            "project": {"type": "string", "enum": projects},
            "summary": {"type": "string", "description": "One line, at most 120 characters. Jira assigns the "
                                                         "ticket number, so do not include a key such as PAY-123."},
            "description": {"type": "string", "description": "What happened and what is needed, in plain sentences"},
            "assignee": {"type": "string", "enum": people},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Short tags such as an incident ID"},
            "sources": {"type": "array", "items": {"type": "string"}, "description": "Tags of the sources used, e.g. S1"},
        }},
    }}


@dataclass
class Draft:
    user: str
    question: str
    project: str
    summary: str
    description: str
    assignee: str | None
    labels: list
    cited: list   # the allowed documents the draft is based on
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "id": self.id, "action": TOOL_NAME, "project": self.project, "summary": self.summary,
            "description": self.description, "assignee": self.assignee, "labels": self.labels,
            "sources": [{"source": d.source, "doc_id": d.doc_id, "title": d.title, "url": d.url,
                         "container": d.container} for d in self.cited],
        }


def creatable_projects(jira, user):
    """Projects where Jira itself lets this person create tickets, checked live, never cached."""
    account = user.get("atlassian_account_id")
    if not account:
        return []
    ids = {str(jira.api.project(key)["id"]): key for key in jira.projects}
    response = jira.api.request("POST", "/rest/api/3/permissions/check", payload={
        "accountId": account,
        "projectPermissions": [{"permissions": ["CREATE_ISSUES"], "projects": [int(i) for i in ids]}],
    })
    allowed = {str(p) for grant in response.get("projectPermissions", []) for p in grant.get("projects", [])}
    return [key for pid, key in ids.items() if pid in allowed]


def propose(args, question, user_name, identities, docs, jira, incident, audit, record):
    """Turn the model's tool call into a draft for the user to confirm, or refuse.
    record: the question's audit data (retrieval and decisions). Returns (draft or None, refusal, audit seq)."""
    projects = creatable_projects(jira, identities[user_name])
    project = args.get("project")
    if project not in projects:
        if not projects:
            refusal = "You can't create tickets in any Jira project, so I didn't draft one."
        elif project:
            refusal = f"You can't create tickets in {project}. You can in {', '.join(projects)}; ask again naming one."
        else:
            refusal = f"I couldn't tell which project to use. You can create tickets in {', '.join(projects)}; ask again naming one."
        seq = audit.append(user_name, "action_denied", {**record, "action": TOOL_NAME, "requested": args,
                                                        "change": f"may not create tickets in {project}"})
        return None, refusal, seq

    people = {name for name, u in identities.items() if u.get("atlassian_account_id")}
    used = {int(m.group(1)) for tag in args.get("sources") or [] if (m := TAG_RE.fullmatch(str(tag)))}
    labels = {str(l) for l in args.get("labels") or [] if LABEL_RE.fullmatch(str(l))} | ({incident} if incident else set())
    draft = Draft(
        user=user_name,
        question=question,
        project=project,
        summary=" ".join(str(args.get("summary") or question).split())[:120],
        description=str(args.get("description") or "").strip()[:3000],
        assignee=args.get("assignee") if args.get("assignee") in people else None,
        labels=sorted(labels)[:5],
        cited=[docs[i - 1] for i in sorted(used) if 1 <= i <= len(docs)],
    )
    with DRAFTS_LOCK:
        for old in [k for k, d in DRAFTS.items() if time.time() - d.created > DRAFT_TTL]:
            del DRAFTS[old]
        DRAFTS[draft.id] = draft
    seq = audit.append(user_name, "action_proposed", {**record, "action": TOOL_NAME, "draft": draft.to_dict()})
    return draft, None, seq


def ticket_description(draft):
    lines = [draft.description, "", "Sources:"]
    lines += [f"- {d.title} ({d.url})" for d in draft.cited] or ["- none"]
    lines += ["", f"Drafted by the Internal Brain for {draft.user}, who reviewed and confirmed it."]
    return "\n".join(lines)


def confirm(draft_id, user_name, create, sources, audit, identities, index=None):
    """Carry out (create=True) or discard a draft. Returns (key, url) once created, or None when cancelled."""
    with DRAFTS_LOCK:
        draft = DRAFTS.get(draft_id)
        if draft is None or draft.user != user_name or time.time() - draft.created > DRAFT_TTL:
            raise PermissionError("This draft has expired or belongs to someone else. Ask again for a new one.")
        del DRAFTS[draft_id]
    if not create:
        audit.append(user_name, "action_cancelled", {"action": TOOL_NAME, "draft": draft.id,
                                                     "change": f"cancelled a draft {draft.project} ticket"})
        return None

    from jira.jira_cli import adf
    jira, user = sources["jira"], identities[user_name]
    if draft.project not in creatable_projects(jira, user):   # access may have changed since the draft
        audit.append(user_name, "action_denied", {"action": TOOL_NAME, "draft": draft.id,
                                                  "change": f"may no longer create tickets in {draft.project}"})
        raise PermissionError(f"You can no longer create tickets in {draft.project}, so nothing was created.")
    fields = {
        "project": {"key": draft.project},
        "issuetype": {"name": ISSUE_TYPE},
        "summary": draft.summary,
        "description": adf(ticket_description(draft)),
        "labels": draft.labels,
        "reporter": {"accountId": user["atlassian_account_id"]},
    }
    if draft.assignee:
        fields["assignee"] = {"accountId": identities[draft.assignee]["atlassian_account_id"]}
    key = jira.api.request("POST", "/rest/api/3/issue", payload={"fields": fields})["key"]
    if index is not None:
        refresh(index, jira, key)   # the next question can find it straight away
    audit.append(user_name, "action_executed", {"action": TOOL_NAME, "draft": draft.to_dict(), "key": key,
                                                "change": f"created {key} in {draft.project}"})
    return key, jira.api.issue_url(key)

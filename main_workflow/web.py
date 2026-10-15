"""Corporate Chat with Dynamic Access: local web UI.

    python3 -m main_workflow.web [--port 8090] [--sync-interval 60]

Serves the assistant at / and the source platform console at /console.
"""

import argparse
import json
import re
import secrets
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import actions, pipeline
from .audit import AuditLog, now_utc
from .cli import parse_since
from .index import Index
from .memory import Memory
from .rehearsal import (CONFLUENCE_CLI, DEMO_DRIVE, DEMO_SPACES, FIXTURE_CLI, GDRIVE_CLI, JIRA_CLI, SLACK_CLI,
                        reset_platforms, run_cli)
from .sources import load_sources
from .sync import refresh, run_once

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
JIRA_STATUS_ORDER = ["To Do", "In Progress", "Done"]
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript"}
ACCOUNT_KEYS = {"confluence": "atlassian_account_id", "jira": "atlassian_account_id",
                "gdrive": "google_email", "slack": "slack_user_id"}

SOURCES = load_sources()
SESSIONS = {}
CLEARED_SESSIONS = set()
SESSIONS_LOCK = threading.Lock()
IDENTITIES_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
ACTIVITY = deque(maxlen=50)
SYNC_STATE = {"last_run": None, "errors": {}}


class SessionGone(Exception):
    pass


def log_activity(kind, text, ok=True):
    ACTIVITY.appendleft({"ts": now_utc(), "kind": kind, "text": text, "ok": ok})


def identities():
    return pipeline.load_identities()


def set_audit_role(name, grant):
    with IDENTITIES_LOCK:
        data = json.loads(pipeline.IDENTITIES.read_text(encoding="utf-8"))
        user = next((u for u in data["users"] if u["name"] == name), None)
        if user is None:
            raise ValueError(f"Unknown user {name!r}")
        if bool(user.get("can_audit")) == grant:
            return f"No change: {name} {'already has' if grant else 'does not have'} the auditor role"
        user["can_audit"] = grant
        tmp = pipeline.IDENTITIES.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(pipeline.IDENTITIES)
    return f"{'Granted' if grant else 'Revoked'} the auditor role {'to' if grant else 'from'} {name}"


def accounts(user):
    # stand-ins match users by name, so everyone has an account there
    return {name: bool(user.get(ACCOUNT_KEYS[name])) if name in ACCOUNT_KEYS else True for name in SOURCES}


CREATED_RE = re.compile(r"\((file|page) ([\w-]+)\)$")


def index_created(text):
    """Index a file or page a console action just created, by its ID ("(file ID)" or "(page ID)" at the end of
    the message), without waiting for Drive's or Confluence's search to list it."""
    m = CREATED_RE.search(text)
    source = SOURCES.get({"file": "gdrive", "page": "confluence"}[m.group(1)]) if m else None
    if source is None:
        return
    with SYNC_LOCK:
        updated, removed = refresh(Index(), source, m.group(2))
    if updated or removed:
        AuditLog().append("system", "sync", {"source": source.name, "updated": updated, "removed": removed, "full": False})
    for u in updated:
        log_activity("sync", f"Indexed {source.name} {u['title']} v{u['version']}")


def sync_now(full=False):
    with SYNC_LOCK:
        results = run_once(Index(), SOURCES, AuditLog(), full=full)
    SYNC_STATE["last_run"] = now_utc()
    for r in results:
        if r.get("error"):
            SYNC_STATE["errors"][r["source"]] = r["error"]
            log_activity("sync", f"{r['source']}: sync failed", ok=False)
            continue
        SYNC_STATE["errors"].pop(r["source"], None)
        for u in r["updated"]:
            log_activity("sync", f"Sync picked up {r['source']} {u['title']} v{u['version']}")
        for doc_id in r["removed"]:
            log_activity("sync", f"Sync removed {r['source']} {doc_id}")
    return results


def sync_loop(interval):
    while True:
        try:
            sync_now()
        except Exception as exc:
            print(f"sync loop error: {exc}", file=sys.stderr)
        time.sleep(interval)


def session_for(handler, body=None):
    sid = handler.headers.get("X-Session") or (body or {}).get("session")
    with SESSIONS_LOCK:
        session = SESSIONS.get(sid)
        cleared = sid in CLEARED_SESSIONS
    if not session:
        if cleared:
            raise SessionGone("This chat was cleared because the rehearsal was reset in the platform console.")
        raise SessionGone("This chat ended because the server restarted.")
    return session


def require_auditor(session):
    user = identities().get(session["user"], {})
    if not user.get("can_audit"):
        AuditLog().append(session["user"], "audit_query_denied", {"via": "web"})
        raise PermissionError("Only auditors can view the audit trail.")
    return user


# assistant API

def api_users(handler, query, body):
    return [
        {"name": u["name"], "role": u["role"], "can_audit": bool(u.get("can_audit")), "accounts": accounts(u)}
        for u in identities().values()
    ]


def api_session(handler, query, body):
    name = body.get("user")
    if name not in identities():
        raise PermissionError(f"Unknown user {name!r}")
    sid = secrets.token_urlsafe(16)
    with SESSIONS_LOCK:
        SESSIONS[sid] = {"user": name, "memory": Memory(name), "lock": threading.Lock()}
    AuditLog().append(name, "sign_in", {"via": "web"})
    return {"session": sid, "user": name}


def api_session_check(handler, query, body):
    session = session_for(handler)
    return {"user": session["user"], "turns": len(session["memory"].turns)}


def api_ask(handler, query, body):
    session = session_for(handler, body)
    question = (body.get("question") or "").strip()
    if not question:
        raise ValueError("Ask a question first.")
    with session["lock"]:
        result = pipeline.run(question, session["user"], SOURCES, AuditLog(), identities(),
                              Index(), session["memory"], allow_actions=True)
    if result.draft:
        return {"draft": result.draft.to_dict(), "audit_seq": result.audit_seq}
    return {
        "answer": result.answer,
        "dropped": bool(result.dropped),
        "dropped_turns": [d["seq"] for d in result.dropped if d.get("seq")],
        "audit_seq": result.audit_seq,
        "citations": [
            {"tag": f"S{i}", "source": d.source, "title": d.title, "url": d.url, "version": d.version,
             "updated_at": d.updated_at, "container": d.container}
            for i, d in result.cited
        ],
    }


def api_action(handler, query, body):
    session = session_for(handler, body)
    with session["lock"]:
        created = actions.confirm(body.get("draft"), session["user"], bool(body.get("create")), SOURCES,
                                  AuditLog(), identities(), Index())
    if not created:
        return {"message": "Cancelled. Nothing was created."}
    key, url = created
    log_activity("action", f"{session['user']} created {key} through the Brain")
    return {"message": f"Created {key}", "key": key, "url": url}


def api_reset_chat(handler, query, body):
    session = session_for(handler, body)
    session["memory"].clear()
    return {"ok": True}


def api_sync(handler, query, body):
    return {"sources": Index().status(), "errors": SYNC_STATE["errors"], "last_run": SYNC_STATE["last_run"]}


def api_audit(handler, query, body):
    session = session_for(handler)
    require_auditor(session)
    q = {k: v[0] for k, v in query.items() if v and v[0]}
    filters = {
        "user": q.get("user"), "since": parse_since(q.get("since")), "event": q.get("event"),
        "source": q.get("source"), "container": q.get("container"), "doc_id": q.get("doc"),
    }
    audit = AuditLog()
    rows = audit.query(**filters)
    audit.append(session["user"], "audit_query", {"via": "web", "filters": filters,
                                                  "returned": [r["seq"] for r in rows]})
    return list(reversed(rows[-200:]))


def api_audit_verify(handler, query, body):
    session = session_for(handler, body)
    require_auditor(session)
    count, problems = AuditLog().verify()
    return {"count": count, "problems": [{"seq": s, "reason": r} for s, r in problems]}


# console API

def api_console_grid(handler, query, body):
    people = list(identities().values())
    docs = Index().all_docs()

    def cell(args):
        doc, user = args
        try:
            return SOURCES[doc.source].can_access(user, doc.doc_id)
        except Exception:
            return None

    pairs = [(d, u) for d in docs if d.source in SOURCES for u in people]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cell, pairs))
    rows, i = [], 0
    for d in docs:
        if d.source not in SOURCES:
            continue
        cells = {}
        for u in people:
            cells[u["name"]] = results[i]
            i += 1
        rows.append({"source": d.source, "doc_id": d.doc_id, "title": d.title,
                     "container": d.container, "version": d.version, "cells": cells})
    return {"users": [u["name"] for u in people], "rows": rows, "checked_at": now_utc()}


def overview_confluence(people):
    """Each space's role per person, from Confluence's own role assignments."""
    from confluence.demo_spaces import Confluence as Spaces, load_seed
    spaces = Spaces(SOURCES["confluence"].api)
    role_names = {v: k for k, v in spaces.roles().items()}
    level_of = {name: level.capitalize() for level, name in load_seed()["levels"].items()}
    names = {u.get("atlassian_account_id"): n for n, u in people.items() if u.get("atlassian_account_id")}
    rows = []
    for space_id, key in SOURCES["confluence"].space_by_id.items():
        cells = {}
        for (ptype, pid), role in spaces.role_assignments(space_id).items():
            if ptype == "USER" and pid in names:
                name = role_names.get(role, "")
                cells[names[pid]] = level_of.get(name, name or "Role")
        rows.append({"name": key, "cells": cells})
    return rows


def overview_jira(people):
    """Project roles per person, plus the PAY Security level, from Jira's own role lists."""
    from jira.jira_cli import load_seed
    api, targets = SOURCES["jira"].api, load_seed()["targets"]
    roles = api.global_roles()
    names = {u.get("atlassian_account_id"): n for n, u in people.items() if u.get("atlassian_account_id")}
    # strongest role first, so a person in several roles shows the highest one
    project_roles = [("Administrators", "Admin"), ("Member", "Edit"), ("Viewer", "View")]
    rows = []
    for target, (key, role) in targets.items():
        shown = project_roles if role == "Member" else [(role, "Member")]
        cells = {}
        for role_name, label in shown:
            if role_name in roles:
                for account in api.role_users(key, roles[role_name]):
                    if account in names:
                        cells.setdefault(names[account], label)
        rows.append({"name": key if role == "Member" else f"{key} {role} level", "cells": cells})
    return rows


def overview_slack(people):
    return [{"name": f"#{channel}", "cells": {n: "Member" for n in members}}
            for channel, members in slack_members().items()]


def overview_drive(people):
    """Each folder's sharing per person, from Drive's own permission lists."""
    from gdrive.demo_drive import load_spec, people as drive_people, resolve
    spec, names = load_spec(), drive_people()
    robot = SOURCES["gdrive"].api
    folders, _ = resolve(robot, spec, names)
    labels = {"owner": "Owner", "writer": "Edit", "commenter": "Comment", "reader": "View"}
    rows = []
    for entry in spec["folders"]:
        folder = folders.get(entry["path"])
        if folder is None:
            continue
        cells = {}
        for p in robot.permissions(folder["id"]):
            n = names.get((p.get("emailAddress") or "").lower())
            if n:
                cells[n] = labels.get(p["role"], p["role"])
        rows.append({"name": entry["path"].rpartition("/")[2], "path": entry["path"],
                     "depth": entry["path"].count("/"), "cells": cells})
    return rows


def api_console_overview(handler, query, body):
    """Per-source rights per person, read live from each platform, so console changes show up straight away."""
    people = identities()
    readers = {"confluence": ("Confluence", overview_confluence), "jira": ("Jira", overview_jira),
               "slack": ("Slack", overview_slack), "gdrive": ("Drive", overview_drive)}
    wanted = [(key, label, fn) for key, (label, fn) in readers.items()
              if key in SOURCES or (key == "slack" and "slack-fixture" in SOURCES)]

    def read(item):
        key, label, fn = item
        try:
            return {"source": key, "label": label, "rows": fn(people)}
        except Exception as exc:
            return {"source": key, "label": label, "rows": [], "error": f"{type(exc).__name__}: {str(exc)[:160]}"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(read, wanted))
    groups.append({"source": "audit", "label": "Chat", "rows": [
        {"name": "Audit trail", "cells": {n: "Auditor" for n, u in people.items() if u.get("can_audit")}}]})
    return {"users": list(people), "groups": groups, "checked_at": now_utc()}


def jira_console_options():
    """Targets, members, tickets, and statuses from real Jira, read live like everything else in the console."""
    from jira.jira_cli import load_seed
    jira = SOURCES["jira"]
    api, targets = jira.api, load_seed()["targets"]
    names = {u.get("atlassian_account_id"): n for n, u in identities().items()}
    roles = api.global_roles()

    def members(target):
        # a project target lists everyone who can open the project, labelled by role; Add/Remove changes Member only
        key, role = targets[target]
        shown = ("Member", "Viewer", "Administrators") if role == "Member" else (role,)
        return target, [f"{n} ({r})" if role == "Member" else n for r in shown
                        for n in sorted(names.get(a, "other account") for a in api.role_users(key, roles[r]))]

    with ThreadPoolExecutor(max_workers=4) as pool:
        jira_members = dict(pool.map(members, targets))
    scope = f"project in ({', '.join(jira.projects)})"
    issues = [i["key"] for i in api.search(f"{scope} ORDER BY created DESC", "summary", limit=50)]
    found = {s["name"] for t in api.request("GET", f"/rest/api/3/project/{jira.projects[0]}/statuses")
             for s in t.get("statuses", [])}
    statuses = [s for s in JIRA_STATUS_ORDER if s in found] + sorted(found - set(JIRA_STATUS_ORDER))
    return {"jira": True, "jira_targets": list(targets), "jira_members": jira_members,
            "issues": issues, "statuses": statuses}


def slack_members():
    """Demo users in each Slack channel: live from Slack, or from the stand-in."""
    if "slack" not in SOURCES:
        from stand_in_jira_slack.sources import load_state
        return {c["name"]: c["members"] for c in load_state()["slack"]["channels"].values()}
    names = {u["slack_user_id"]: u["name"] for u in identities().values() if u.get("slack_user_id")}
    return {channel: sorted(names[m] for m in members if m in names)
            for channel, members in SOURCES["slack"].channel_members().items()}


def api_console_options(handler, query, body):
    jira ={"jira": False, "jira_targets": [], "jira_members": {}, "issues": [], "statuses": []}
    if "jira" in SOURCES:
        try:
            jira = jira_console_options()
        except Exception as exc:
            log_activity("jira", f"Jira options unavailable: {str(exc)[:120]}", ok=False)
    slack = slack_members()
    return {
        "users": list(identities()),
        "channels": list(slack),
        "channel_members": slack,
        **jira,
        "drive": "gdrive" in SOURCES,
        "slack_stand_in": "slack-fixture" in SOURCES,
        "auditors": [u["name"] for u in identities().values() if u.get("can_audit")],
    }


def api_console_feed(handler, query, body):
    gate = AuditLog().recent(15, events=("query", "context_dropped"))
    return {"activity": list(ACTIVITY), "gate": gate}


def api_console_action(handler, query, body):
    action = body.get("action")
    if action == "slack_access":
        verb = "grant" if body.get("grant") else "revoke"
        if "slack" in SOURCES:
            ok, text = run_cli([SLACK_CLI, verb, body["user"], body["channel"]])
        else:
            ok, text = run_cli([FIXTURE_CLI, verb, body["user"], "slack", body["channel"]])
    elif action == "jira_access":
        verb = "grant" if body.get("grant") else "revoke"
        ok, text = run_cli([JIRA_CLI, verb, body["user"], body["target"]])
    elif action == "jira_status":
        ok, text = run_cli([JIRA_CLI, "set-status", body["key"], body["status"]])
    elif action == "drive_access":
        if body.get("grant"):
            ok, text = run_cli([GDRIVE_CLI, "share", body["user"], "--role", body.get("role", "viewer")])
        else:
            ok, text = run_cli([GDRIVE_CLI, "unshare", body["user"]])
    elif action == "drive_upload":
        # uploaded with the owner's own Google sign-in, so Drive itself decides whether they may
        ok, text = run_cli([DEMO_DRIVE, "upload", str(int(body["step"])), body["owner"]], 300)
        if ok:
            index_created(text)
    elif action == "incident_report":
        ok, text = run_cli([DEMO_SPACES, "incident-report"], 300)
        if ok:
            index_created(text)
    elif action == "audit_role":
        ok, text = True, set_audit_role(body["user"], bool(body.get("grant")))
    elif action == "runbook_update":
        ok, text = run_cli([CONFLUENCE_CLI, "update-runbook"])
    elif action == "runbook_restore":
        ok, text = run_cli([CONFLUENCE_CLI, "restore-runbook"])
    elif action == "sync_now":
        results = sync_now()
        changed = sum(len(r.get("updated", [])) + len(r.get("removed", [])) for r in results)
        ok, text = all(not r.get("error") for r in results), f"Sync finished: {changed} change(s)"
    elif action == "reset":
        ok, text = reset_platforms(SOURCES)
        sync_now(full=True)   # drop deleted tickets and threads from the index
        with SESSIONS_LOCK:
            CLEARED_SESSIONS.update(SESSIONS)
            SESSIONS.clear()
        if "main_workflow.slack_bot" in sys.modules:   # /brain chats too, if the bot is running
            sys.modules["main_workflow.slack_bot"].MEMORIES.clear()
        text += "; index re-synced; all chats cleared"
    else:
        raise ValueError(f"Unknown action {action!r}")
    log_activity(action, text, ok)
    return {"ok": ok, "message": text}


ROUTES = {
    ("GET", "/api/users"): api_users,
    ("POST", "/api/session"): api_session,
    ("GET", "/api/session"): api_session_check,
    ("POST", "/api/ask"): api_ask,
    ("POST", "/api/action"): api_action,
    ("POST", "/api/reset-chat"): api_reset_chat,
    ("GET", "/api/sync"): api_sync,
    ("GET", "/api/audit"): api_audit,
    ("POST", "/api/audit/verify"): api_audit_verify,
    ("GET", "/api/console/grid"): api_console_grid,
    ("GET", "/api/console/overview"): api_console_overview,
    ("GET", "/api/console/options"): api_console_options,
    ("GET", "/api/console/feed"): api_console_feed,
    ("POST", "/api/console/action"): api_console_action,
}
PAGES = {"/": "index.html", "/console": "console.html"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        url = urlparse(self.path)
        route = ROUTES.get((method, url.path))
        if route is None:
            return self._static(url.path) if method == "GET" else self._send(404, {"error": "Not found"})
        try:
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, route(self, parse_qs(url.query), body))
        except SessionGone as exc:
            self._send(401, {"error": str(exc)})
        except PermissionError as exc:
            self._send(403, {"error": str(exc)})
        except (ValueError, KeyError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _static(self, path):
        name = PAGES.get(path) or (path[len("/static/"):] if path.startswith("/static/") else None)
        file = (STATIC / name).resolve() if name else None
        if not file or STATIC not in file.parents or not file.is_file():
            return self._send(404, {"error": "Not found"})
        self._send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def log_message(self, fmt, *args):
        if "/api/console/feed" not in self.path and "/api/sync" not in self.path:
            sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")


def main():
    parser = argparse.ArgumentParser(prog="main_workflow.web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--sync-interval", type=int, default=60)
    parser.add_argument("--keep-state", action="store_true", help="keep the current stand-in Jira/Slack data")
    args = parser.parse_args()

    if not args.keep_state:
        ok, text = run_cli([FIXTURE_CLI, "reset"])
        log_activity("reset", f"Server start: {text}", ok)

    threading.Thread(target=sync_loop, args=(args.sync_interval,), daemon=True).start()
    if "slack" in SOURCES:
        from .slack_bot import start as start_slack_bot
        start_slack_bot(SOURCES, log_activity)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Corporate Chat with Dynamic Access on http://{args.host}:{args.port}  (console: /console)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

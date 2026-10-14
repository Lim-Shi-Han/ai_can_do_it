"""Corporate Chat with Dynamic Access: local web UI.

    python3 -m main_workflow.web [--port 8090] [--sync-interval 60]

Serves the assistant at / and the source platform console at /console.
"""

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import pipeline
from .audit import AuditLog, now_utc
from .cli import parse_since
from .index import Index
from .memory import Memory
from .sources import load_sources
from .sync import run_once

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
STATIC = ROOT / "static"
FIXTURE_CLI = REPO / "stand_in_jira_slack" / "fixture_cli.py"
JIRA_CLI = REPO / "jira" / "jira_cli.py"
JIRA_STATUS_ORDER = ["To Do", "In Progress", "Done"]
GDRIVE_CLI = REPO / "gdrive" / "gdrive_cli.py"
CONFLUENCE_CLI = REPO / "confluence" / "confluence_cli.py"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript"}

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
    out = {}
    for name in SOURCES:
        if name in ("confluence", "jira"):
            out[name] = bool(user.get("atlassian_account_id"))
        elif name == "gdrive":
            out[name] = bool(user.get("google_email"))
        else:
            out[name] = True
    return out


def sync_now():
    with SYNC_LOCK:
        results = run_once(Index(), SOURCES, AuditLog())
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


def run_cli(args):
    done = subprocess.run([sys.executable, *map(str, args)], cwd=REPO, capture_output=True, text=True, timeout=120)
    if done.returncode == 0:
        return True, (done.stdout.strip() or "done").splitlines()[0]
    return False, (done.stderr.strip() or done.stdout.strip() or "failed").splitlines()[-1]


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
                              Index(), session["memory"])
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


def api_console_options(handler, query, body):
    from stand_in_jira_slack.sources import load_state
    state = load_state()
    jira = {"jira": False, "jira_targets": [], "jira_members": {}, "issues": [], "statuses": []}
    if "jira" in SOURCES:
        try:
            jira = jira_console_options()
        except Exception as exc:
            log_activity("jira", f"Jira options unavailable: {str(exc)[:120]}", ok=False)
    return {
        "users": list(identities()),
        "channels": [c["name"] for c in state["slack"]["channels"].values()],
        "channel_members": {c["name"]: c["members"] for c in state["slack"]["channels"].values()},
        **jira,
        "drive": "gdrive" in SOURCES,
        "auditors": [u["name"] for u in identities().values() if u.get("can_audit")],
    }


def api_console_feed(handler, query, body):
    gate = AuditLog().recent(15, events=("query", "context_dropped"))
    return {"activity": list(ACTIVITY), "gate": gate}


def api_console_action(handler, query, body):
    action = body.get("action")
    if action == "slack_access":
        verb = "grant" if body.get("grant") else "revoke"
        ok, text = run_cli([FIXTURE_CLI, verb, body["user"], "slack", body["channel"]])
    elif action == "jira_access":
        verb = "grant" if body.get("grant") else "revoke"
        ok, text = run_cli([JIRA_CLI, verb, body["user"], body["target"]])
    elif action == "jira_status":
        ok, text = run_cli([JIRA_CLI, "set-status", body["key"], body["status"]])
    elif action == "drive_access":
        ok, text = run_cli([GDRIVE_CLI, "share" if body.get("grant") else "unshare", body["user"]])
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
        ok, text = run_cli([FIXTURE_CLI, "reset"])
        if "jira" in SOURCES:
            # roles, statuses, and comments back to the seed; tickets created during a demo need jira_cli.py rebuild
            jira_ok, jira_text = run_cli([JIRA_CLI, "reset"])
            ok, text = ok and jira_ok, f"{text}; {jira_text}"
        runbook_ok, runbook_text = run_cli([CONFLUENCE_CLI, "restore-runbook"])
        ok, text = ok and runbook_ok, f"{text}; {runbook_text}"
        engineer = identities().get("ShiHan", {})
        if ok and "gdrive" in SOURCES and engineer.get("google_email"):
            ok, drive_text = run_cli([GDRIVE_CLI, "share", "ShiHan"])
            text += f"; {drive_text}"
        with SESSIONS_LOCK:
            CLEARED_SESSIONS.update(SESSIONS)
            SESSIONS.clear()
        text += "; all chats cleared"
    else:
        raise ValueError(f"Unknown action {action!r}")
    log_activity(action, text, ok)
    return {"ok": ok, "message": text}


ROUTES = {
    ("GET", "/api/users"): api_users,
    ("POST", "/api/session"): api_session,
    ("GET", "/api/session"): api_session_check,
    ("POST", "/api/ask"): api_ask,
    ("POST", "/api/reset-chat"): api_reset_chat,
    ("GET", "/api/sync"): api_sync,
    ("GET", "/api/audit"): api_audit,
    ("POST", "/api/audit/verify"): api_audit_verify,
    ("GET", "/api/console/grid"): api_console_grid,
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
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Corporate Chat with Dynamic Access on http://{args.host}:{args.port}  (console: /console)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

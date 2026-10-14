import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import pipeline
from .audit import DEFAULT_DB as AUDIT_DB, AuditLog
from .index import DEFAULT_DB as INDEX_DB, Index
from .memory import Memory
from .rehearsal import reset_platforms
from .sources import load_sources


def print_result(result):
    if result.dropped:
        print("\n(Earlier answers were removed from this chat: their sources changed or are no longer available to you.)")
    print(f"\n{result.answer}\n")
    if result.cited:
        print("Sources:")
        for i, doc in result.cited:
            print(f"  [S{i}] {doc.title} ({doc.source}, v{doc.version}, updated {doc.updated_at})")
            print(f"       {doc.url}")
    print(f"(audit #{result.audit_seq})")


def parse_since(value):
    if not value:
        return None
    m = re.fullmatch(r"(\d+)([dhm])", value)
    if m:
        unit = {"d": "days", "h": "hours", "m": "minutes"}[m.group(2)]
        start = datetime.now(timezone.utc) - timedelta(**{unit: int(m.group(1))})
        return start.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return value


def cmd_ask(args, audit):
    result = pipeline.run(args.question, args.user, load_sources(), audit, index=Index())
    print_result(result)


def cmd_chat(args, audit):
    sources, index = load_sources(), Index()
    identities = pipeline.load_identities()
    user = args.user
    if user not in identities:
        print(f"No such user: {user}")
        return
    memory = Memory(user)
    print(f"Signed in as {user}. /as <name> switches user, /reset clears the chat, /quit leaves.")
    while True:
        try:
            line = input(f"{user}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            return
        if line == "/reset":
            memory.clear()
            print("Chat cleared.")
            continue
        if line.startswith("/as "):
            name = line[4:].strip()
            if name not in identities:
                print(f"No such user: {name}")
                continue
            audit.append(name, "switch_user", {"from": user})
            user, memory = name, Memory(name)
            print(f"Now signed in as {user} ({identities[user]['role']}). Chat history starts empty.")
            continue
        try:
            print_result(pipeline.run(line, user, sources, audit, identities, index, memory))
        except Exception as exc:
            print(f"Error: {exc}")


def cmd_audit_verify(args, audit):
    count, problems = audit.verify()
    if not problems:
        print(f"OK: {count} entries, hash chain intact")
        return
    print(f"TAMPERED: {len(problems)} problem(s) in {count} entries")
    for seq, reason in problems:
        print(f"  #{seq}: {reason}")
    sys.exit(2)


def cmd_audit_query(args, audit):
    identities = pipeline.load_identities()
    requester = identities.get(args.user)
    filters = {
        "user": args.target, "since": parse_since(args.since), "event": args.event,
        "source": args.source, "container": args.container, "doc_id": args.doc,
    }
    if not requester or not requester.get("can_audit"):
        audit.append(args.user, "audit_query_denied", {"filters": filters})
        print("You are not allowed to query the audit trail.")
        sys.exit(1)

    rows = audit.query(**filters)
    audit.append(args.user, "audit_query", {"filters": filters, "returned": [r["seq"] for r in rows]})
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for r in rows:
        data = r["data"]
        print(f"#{r['seq']} {r['ts']} {r['user']} {r['event']}")
        if "question" in data:
            print(f"  asked:   {data['question']}")
        for d in r["matched"] or data.get("decisions", []):
            verdict = "ALLOW" if d["allowed"] else "DENY "
            print(f"  {verdict}  {d['source']}:{d['doc_id']} v{d.get('version') or '-'}  {d['title']}  ({d['reason']})")
        if data.get("cited"):
            print("  cited:   " + ", ".join(f"{c['source']}:{c['doc_id']} v{c['version']}" for c in data["cited"]))
        if "answer" in data:
            print("  answer:  " + data["answer"].replace("\n", " ")[:300])
    print(f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}")


def cmd_reset(args, audit):
    """Back to the demo's base state. Through the running web server, which also clears every chat; with no
    server running, directly, and the audit trail and search index are cleared too."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/api/console/action",
        data=json.dumps({"action": "reset"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        sys.exit(f"Reset failed: {exc.read(300).decode('utf-8', errors='replace')}")
    except urllib.error.URLError:
        print("No web server running: resetting the platforms directly, then clearing the audit trail and search index.")
        ok, text = reset_platforms(load_sources())
        print(text)
        audit.db.close()
        for path in (AUDIT_DB, AUDIT_DB.with_suffix(".head"), INDEX_DB):
            path.unlink(missing_ok=True)
        sys.exit(0 if ok else 1)
    print(result["message"])
    sys.exit(0 if result["ok"] else 1)


def main():
    parser = argparse.ArgumentParser(prog="main_workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask")
    ask.add_argument("--as", dest="user", required=True)
    ask.add_argument("question")
    ask.set_defaults(func=cmd_ask)

    chat = sub.add_parser("chat")
    chat.add_argument("--as", dest="user", required=True)
    chat.set_defaults(func=cmd_chat)

    reset = sub.add_parser("reset", help="reset Jira, Slack, Confluence, and Drive (and every chat, if the web server is running)")
    reset.add_argument("--port", type=int, default=8090, help="the web server's port")
    reset.set_defaults(func=cmd_reset)

    audit_p = sub.add_parser("audit")
    audit_sub = audit_p.add_subparsers(dest="audit_command", required=True)
    verify = audit_sub.add_parser("verify")
    verify.set_defaults(func=cmd_audit_verify)
    query = audit_sub.add_parser("query")
    query.add_argument("--as", dest="user", required=True)
    query.add_argument("--user", dest="target")
    query.add_argument("--since", help="30d, 12h, 15m, or an ISO timestamp")
    query.add_argument("--event")
    query.add_argument("--source")
    query.add_argument("--container", help="Confluence space, Jira project, Slack channel, or Drive folder")
    query.add_argument("--doc")
    query.add_argument("--json", action="store_true")
    query.set_defaults(func=cmd_audit_query)

    args = parser.parse_args()
    args.func(args, AuditLog())


if __name__ == "__main__":
    main()

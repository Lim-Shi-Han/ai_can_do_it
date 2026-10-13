#!/usr/bin/env python3
"""Inspect and change the stand-in Jira and Slack data during a demo."""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from stand_in_jira_slack.sources import (  # noqa: E402
    SEED, STATE, JiraFixtureSource, SlackFixtureSource, load_state, now_utc, save_state,
)

IDENTITIES = Path(os.environ.get("IDENTITIES_FILE") or ROOT.parent / "main_workflow" / "identities.json")


def users():
    return [u for u in json.loads(IDENTITIES.read_text(encoding="utf-8"))["users"]]


def channel_id(state, name):
    name = name.lstrip("#")
    for cid, channel in state["slack"]["channels"].items():
        if channel["name"] == name or cid == name:
            return cid
    raise SystemExit(f"No Slack channel {name!r}")


def cmd_status(args):
    people = users()
    print(f"{'document':<62}" + "".join(f"{u['name']:>9}" for u in people))
    for source in (JiraFixtureSource(), SlackFixtureSource()):
        for c in source.changes_since(None):
            row = "".join(f"{'✓' if source.can_access(u, c.doc_id) else '·':>9}" for u in people)
            label = f"{source.name.split('-')[0]} v{c.version} {c.title}"
            print(f"{label[:61]:<62}{row}")


def cmd_access(args, grant):
    state = load_state()
    if args.platform == "slack":
        members = state["slack"]["channels"][channel_id(state, args.target)]["members"]
        where = f"#{args.target.lstrip('#')}"
    elif args.target in state["jira"]["projects"]:
        members = state["jira"]["projects"][args.target]["browse"]
        where = f"Jira project {args.target}"
    elif args.target in state["jira"]["security_levels"]:
        members = state["jira"]["security_levels"][args.target]
        where = f"Jira security level {args.target}"
    else:
        raise SystemExit(f"No Jira project or security level {args.target!r}")

    if grant and args.user not in members:
        members.append(args.user)
    elif not grant and args.user in members:
        members.remove(args.user)
    else:
        print(f"No change: {args.user} {'already has' if grant else 'does not have'} access to {where}")
        return
    save_state(state)
    print(f"{'Granted' if grant else 'Revoked'} {args.user} {'on' if grant else 'from'} {where}")


def cmd_set_status(args):
    state = load_state()
    issue = next((i for i in state["jira"]["issues"] if i["key"] == args.key), None)
    if not issue:
        raise SystemExit(f"No issue {args.key}")
    issue["status"] = args.status
    if args.comment:
        issue["comments"].append({"author": args.author, "at": now_utc(), "text": args.comment})
    issue["version"] += 1
    issue["updated_at"] = now_utc()
    save_state(state)
    print(f"{args.key} is now {args.status} (v{issue['version']})")


def cmd_post(args):
    state = load_state()
    cid = channel_id(state, args.channel)
    ts = f"{time.time():.6f}"
    message = {"user": args.user, "ts": ts, "text": args.text}
    if args.thread:
        thread = next((t for t in state["slack"]["threads"] if t["channel"] == cid and t["ts"] == args.thread), None)
        if not thread:
            raise SystemExit(f"No thread {args.thread} in #{args.channel.lstrip('#')}")
        thread["messages"].append(message)
        thread["version"] += 1
    else:
        thread = {"channel": cid, "ts": ts, "messages": [message], "version": 1}
        state["slack"]["threads"].append(thread)
    thread["updated_at"] = now_utc()
    save_state(state)
    print(f"Posted to #{args.channel.lstrip('#')} thread {thread['ts']} (v{thread['version']})")


def cmd_reset(args):
    shutil.copyfile(SEED, STATE)
    print("Stand-in data reset from seed.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="who can see what").set_defaults(func=cmd_status)
    sub.add_parser("reset", help="restore seed data").set_defaults(func=cmd_reset)

    for name, grant in (("grant", True), ("revoke", False)):
        p = sub.add_parser(name, help=f"{name} access to a Slack channel, Jira project, or Jira security level")
        p.add_argument("user")
        p.add_argument("platform", choices=["slack", "jira"])
        p.add_argument("target", help="channel name, project key, or security level")
        p.set_defaults(func=lambda a, g=grant: cmd_access(a, g))

    p = sub.add_parser("set-status", help="change a Jira issue's status")
    p.add_argument("key")
    p.add_argument("status")
    p.add_argument("--comment")
    p.add_argument("--author", default="ShiHan")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("post", help="post a Slack message, as a reply when --thread is given")
    p.add_argument("channel")
    p.add_argument("user")
    p.add_argument("text")
    p.add_argument("--thread", help="root ts of the thread to reply in")
    p.set_defaults(func=cmd_post)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

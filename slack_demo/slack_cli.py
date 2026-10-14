#!/usr/bin/env python3
"""Set up and drive the real Slack side of the demo, posting as the demo users themselves.

    python3 slack_demo/slack_cli.py login Zhao               # prints the approval link
    python3 slack_demo/slack_cli.py login Zhao "<address>"   # saves Zhao's token to .env
    python3 slack_demo/slack_cli.py reset                    # channels, members, bot, steps 1-3 posted fresh
    python3 slack_demo/slack_cli.py play 5                   # post a later step's messages during the demo
    python3 slack_demo/slack_cli.py status
    python3 slack_demo/slack_cli.py revoke ShiHan payment-incident-001
    python3 slack_demo/slack_cli.py grant ShiHan payment-incident-001
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from slack_sdk import WebClient  # noqa: E402
from slack_sdk.errors import SlackApiError  # noqa: E402
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler  # noqa: E402

from main_workflow.sources.slack import ENV_FILE, load_local_env  # noqa: E402

IDENTITIES = Path(os.environ.get("IDENTITIES_FILE") or ROOT.parent / "main_workflow" / "identities.json")
REDIRECT = "https://localhost/slack-login"
USER_SCOPES = "chat:write,channels:read,groups:read,channels:history,groups:history,channels:write,groups:write"
ADMIN = "Zhao"   # the CTO's admin account (DEMO_PLAN.md); a Slack workspace admin, so it can remove members

# Who is in each channel. #vendor-payprocessor stands in for a Slack Connect channel shared with the
# payment processor (Terrance); Slack Connect needs a paid plan.
CHANNELS = {
    "vendor-payprocessor": {"private": True, "members": ["Terrance", "Zhao", "Sheldon", "ShiHan"]},
    "payment-incident-001": {"private": True, "members": ["Zhao", "ShiHan", "Ivan"]},
    "payments": {"private": False, "members": ["Zhao", "ShiHan", "Ivan", "Sheldon"]},
}
# Slack messages for each step of the demo flow, as (channel, thread) pairs; the first message of a
# thread is its root. Nothing in #vendor-payprocessor may say "incident", "report", "security",
# "breach", or INC-PAY-001, or Terrance's step 9 question would find it and get an answer instead of
# the neutral reply.
STEPS = {
    1: [
        ("payments", [
            ("Zhao", "[deploy-bot] 14:07: payment-service config rollout started (connection-limit change)."),
        ]),
        ("vendor-payprocessor", [
            ("Terrance", "Authorization timeouts from your endpoint spiking since ~14:10."),
            ("Zhao", "Seen, thanks. Checking payment-service on our side now."),
        ]),
    ],
    2: [
        ("payment-incident-001", [
            ("Zhao", "Opened INC-PAY-001, tracked in PAY-100: payment timeouts reported by our processor since ~14:10. "
                     "ShiHan is on call and owns it. Ivan, please join for security."),
        ]),
    ],
    3: [
        ("vendor-payprocessor", [
            ("Zhao", "Could you share your timeout logs? Sheldon is setting up temporary access to our case folder."),
            ("Sheldon", "Opened PAY-102 for temporary vendor access and Zhao approved it. I've shared the case folder in Drive with you."),
            ("Terrance", "Uploaded our processor timeout log: failed authorizations per minute from 14:10."),
        ]),
    ],
    5: [
        ("payment-incident-001", [
            ("ShiHan", "Likely cause: the 14:07 payment-service connection-limit rollout. "
                       "Opened PAY-101 to roll it back. Ivan, can you approve here and on PAY-100?"),
            ("Ivan", "Approved, here and on PAY-100."),
            ("ShiHan", "Rollouts paused. Rollback started at 14:37."),
        ]),
    ],
    6: [
        ("payment-incident-001", [
            ("ShiHan", "15:02: rollback complete and payments have recovered. PAY-101 is done and PAY-100 is resolved."),
            ("Ivan", "Thanks. I'll write up the incident report and open the follow-up tickets."),
        ]),
    ],
    7: [
        ("vendor-payprocessor", [
            ("Terrance", "Sheldon, I can only reconcile our side of the failed payments. "
                         "Could you share Company A's payment records for the same window?"),
            ("Sheldon", "Uploaded our internal payment ledger extract to the case folder. Tracking the reconciliation in PAY-103."),
        ]),
    ],
    8: [
        ("payments", [
            ("Zhao", "PAY-100 and PAY-103 are closed, and the processor can still read our internal ledger extract. "
                     "They don't need our folder any more. Sheldon, please remove their access."),
            ("Sheldon", "Done: unshared the folder from the processor and closed PAY-102 (access revoked, case closed)."),
        ]),
    ],
}
SEEDED = (1, 2, 3)   # posted by reset; the rest are posted with `play` at their point in the demo

def people():
    return {u["name"]: u["slack_user_id"] for u in json.loads(IDENTITIES.read_text(encoding="utf-8"))["users"]}


def token_key(name):
    return f"SLACK_USER_TOKEN_{name.upper()}"


def client(name):
    token = os.environ.get(token_key(name))
    if not token:
        raise SystemExit(f"No Slack token for {name}: run `login {name}` first")
    api = WebClient(token=token)
    api.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    return api


def save_env(key, value):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != key] + [f"{key}={value}"]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def channel_ids(admin):
    pages = admin.conversations_list(types="public_channel,private_channel", exclude_archived=True, limit=200)
    return {c["name"]: c["id"] for page in pages for c in page["channels"]}


def channel_id(admin, name):
    ids = channel_ids(admin)
    if name.lstrip("#") not in ids:
        raise SystemExit(f"No channel #{name.lstrip('#')} that {ADMIN} can see: run reset first")
    return ids[name.lstrip("#")]


def set_members(admin, cid, wanted):
    current = {m for page in admin.conversations_members(channel=cid, limit=200) for m in page["members"]}
    if wanted - current:
        admin.conversations_invite(channel=cid, users=",".join(sorted(wanted - current)))
    for user in current - wanted:
        admin.conversations_kick(channel=cid, user=user)


def wipe(admin, cid):
    """Delete every message, replies before their thread, so each reset starts from fresh threads."""
    authors = {uid: name for name, uid in people().items() if os.environ.get(token_key(name))}
    for page in admin.conversations_history(channel=cid, limit=200):
        for root in page["messages"]:
            thread = admin.conversations_replies(channel=cid, ts=root["ts"], limit=200)["messages"] if root.get("reply_count") else [root]
            for m in reversed(thread):
                if m.get("subtype"):   # joins and the like
                    continue
                try:
                    client(authors.get(m.get("user"), ADMIN)).chat_delete(channel=cid, ts=m["ts"])
                except SlackApiError as exc:
                    print(f"Could not delete a message in {cid}: {exc.response['error']}")


def post_step(channels, step):
    for name, messages in STEPS[step]:
        root = None
        for author, text in messages:
            ts = client(author).chat_postMessage(channel=channels[name], text=text, thread_ts=root)["ts"]
            root = root or ts


def cmd_login(args):
    client_id, secret = os.environ.get("SLACK_DEMO_CLIENT_ID"), os.environ.get("SLACK_DEMO_CLIENT_SECRET")
    if not client_id or not secret:
        raise SystemExit("Set SLACK_DEMO_CLIENT_ID and SLACK_DEMO_CLIENT_SECRET in .env (see slack_demo/README.md)")
    if not args.address:
        query = urlencode({"client_id": client_id, "user_scope": USER_SCOPES, "redirect_uri": REDIRECT})
        print(f"In a browser signed in to Slack as {args.user}, open this link and click Allow:\n\n"
              f"  https://slack.com/oauth/v2/authorize?{query}\n\n"
              "The page then fails to load localhost. That is expected. Copy its address and run:\n\n"
              f'  python3 slack_demo/slack_cli.py login {args.user} "<address>"')
        return
    code = parse_qs(urlparse(args.address).query).get("code", [""])[0]
    if not code:
        raise SystemExit("That address has no code in it. Copy the whole address after clicking Allow.")
    authed = WebClient().oauth_v2_access(client_id=client_id, client_secret=secret, code=code,
                                         redirect_uri=REDIRECT)["authed_user"]
    if authed["id"] != people()[args.user]:
        raise SystemExit(f"That approval came from Slack user {authed['id']}, not {args.user}. "
                         f"Sign in to Slack as {args.user} and try again.")
    save_env(token_key(args.user), authed["access_token"])
    print(f"Saved {args.user}'s token to .env")


def ensure_channels(admin):
    """Create the demo channels if missing and set exactly their members, plus the Brain's bot."""
    if not os.environ.get("SLACK_BOT_TOKEN"):
        raise SystemExit("Set SLACK_BOT_TOKEN in .env first, so the bot can be invited")
    ids = people()
    bot = WebClient(token=os.environ["SLACK_BOT_TOKEN"]).auth_test()["user_id"]
    channels = channel_ids(admin)
    for name, spec in CHANNELS.items():
        if name not in channels:
            channels[name] = admin.conversations_create(name=name, is_private=spec["private"])["channel"]["id"]
        set_members(admin, channels[name], {ids[n] for n in spec["members"]} | {bot})
    return channels


def cmd_reset(args):
    admin = client(ADMIN)
    channels = ensure_channels(admin)
    for name in CHANNELS:
        wipe(admin, channels[name])
    for step in SEEDED:
        post_step(channels, step)
    print(f"Reset {', '.join('#' + n for n in CHANNELS)}: members set, bot invited, steps {', '.join(map(str, SEEDED))} posted")


def cmd_play(args):
    channels = channel_ids(client(ADMIN))
    missing = [name for name, _ in STEPS[args.step] if name not in channels]
    if missing:
        raise SystemExit(f"Missing #{', #'.join(missing)}: run reset first")
    post_step(channels, args.step)
    print(f"Posted step {args.step} in #{', #'.join(dict.fromkeys(name for name, _ in STEPS[args.step]))}")


def cmd_status(args):
    admin, names = client(ADMIN), {uid: name for name, uid in people().items()}
    channels = channel_ids(admin)
    for name, spec in CHANNELS.items():
        if name not in channels:
            print(f"#{name}: missing, run reset")
            continue
        members = {m for page in admin.conversations_members(channel=channels[name], limit=200) for m in page["members"]}
        print(f"#{name} ({'private' if spec['private'] else 'public'}): "
              + ", ".join(sorted(names.get(m, f"{m} (bot or unlinked)") for m in members)))


def cmd_access(args, grant):
    admin, user = client(ADMIN), people()[args.user]
    cid = channel_id(admin, args.channel)
    try:
        if grant:
            admin.conversations_invite(channel=cid, users=user)
        else:
            admin.conversations_kick(channel=cid, user=user)
    except SlackApiError as exc:
        if exc.response["error"] not in ("already_in_channel", "not_in_channel"):
            raise
        print(f"No change: {args.user} {'is already' if grant else 'is not'} in #{args.channel.lstrip('#')}")
        return
    print(f"{'Added' if grant else 'Removed'} {args.user} {'to' if grant else 'from'} #{args.channel.lstrip('#')}")


def main():
    load_local_env()
    users = list(people())
    parser = argparse.ArgumentParser(prog="slack_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="save a demo user's Slack token to .env")
    login.add_argument("user", choices=users)
    login.add_argument("address", nargs="?", help="the address the browser landed on after Allow")
    login.set_defaults(func=cmd_login)

    sub.add_parser("reset", help="create the channels, set members, invite the bot, post steps 1-3 fresh").set_defaults(func=cmd_reset)
    play = sub.add_parser("play", help="post a step's Slack messages during the demo")
    play.add_argument("step", type=int, choices=sorted(set(STEPS) - set(SEEDED)))
    play.set_defaults(func=cmd_play)
    sub.add_parser("status", help="who is in each demo channel").set_defaults(func=cmd_status)
    for verb, grant in (("grant", True), ("revoke", False)):
        p = sub.add_parser(verb, help=f"{'add a user to' if grant else 'remove a user from'} a channel")
        p.add_argument("user", choices=users)
        p.add_argument("channel")
        p.set_defaults(func=lambda args, grant=grant: cmd_access(args, grant))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

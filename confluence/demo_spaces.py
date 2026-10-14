#!/usr/bin/env python3
"""Set up the demo's Confluence spaces, who can use them, and their pages (HANDBOOK, PAYOPS, FINOPS, SECOPS)."""

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

# Confluence is on the same Atlassian site as Jira, so it shares the client and the per-person tokens
from confluence.confluence_cli import storage_to_text  # noqa: E402
from jira.jira_cli import Jira, account_id, author_clients, load_local_env, load_people, now_sgt  # noqa: E402

SEED = ROOT / "demo_spaces.json"
OPEN_TO_ALL = {"all-licensed-users", "anonymous"}  # access classes that would open a space to every user


def load_seed():
    return json.loads(SEED.read_text(encoding="utf-8"))


def storage(text):
    """A small text format to Confluence storage HTML: '## ' headings, '- ' bullets, '1. ' numbered items,
    '**bold**', and plain lines as paragraphs."""
    out, open_list = [], None

    def inline(s):
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(s, quote=False))

    def close():
        nonlocal open_list
        if open_list:
            out.append(f"</{open_list}>")
            open_list = None

    for raw in text.strip().splitlines():
        line = raw.strip()
        kind = "ul" if line.startswith("- ") else "ol" if re.match(r"^\d+\. ", line) else None
        if kind:
            if open_list != kind:
                close()
                out.append(f"<{kind}>")
                open_list = kind
            out.append(f"<li>{inline(re.sub(r'^(- |\d+\. )', '', line))}</li>")
            continue
        close()
        if not line:
            continue
        heading = re.match(r"^(#{2,3}) (.*)", line)
        if heading:
            out.append(f"<h{len(heading.group(1))}>{inline(heading.group(2))}</h{len(heading.group(1))}>")
        else:
            out.append(f"<p>{inline(line)}</p>")
    close()
    return "".join(out)


class Confluence:
    def __init__(self, api):
        self.api = api

    def get_all(self, path, params=None):
        out, params = [], dict(params or {}, limit=250)
        while path:
            data = self.api.request("GET", path, params)
            out += data.get("results", [])
            path, params = data.get("_links", {}).get("next"), None
        return out

    def space(self, key):
        found = self.api.request("GET", "/wiki/api/v2/spaces", {"keys": key}).get("results", [])
        return found[0] if found else None

    def pages(self, space_id):
        return self.get_all(f"/wiki/api/v2/spaces/{space_id}/pages", {"status": "current"})

    def roles(self):
        return {r["name"]: r["id"] for r in self.get_all("/wiki/api/v2/space-roles")}

    def role_assignments(self, space_id):
        """{(principal type, principal id): role id}. This site uses space roles, not individual permissions."""
        return {(a["principal"]["principalType"], a["principal"]["principalId"]): a.get("roleId")
                for a in self.get_all(f"/wiki/api/v2/spaces/{space_id}/role-assignments")}

    def can_read(self, account, content_id):
        res = self.api.request("POST", f"/wiki/rest/api/content/{content_id}/permission/check", payload={
            "subject": {"type": "user", "identifier": account}, "operation": "read"})
        return res.get("hasPermission") is True


# setup: spaces and permissions

def ensure_space(conf, spec):
    space = conf.space(spec["key"])
    if space:
        return space
    conf.api.request("POST", "/wiki/rest/api/space", payload={
        "key": spec["key"], "name": spec["name"],
        "description": {"plain": {"value": spec["description"], "representation": "plain"}},
    })
    print(f"Created space {spec['key']} ({spec['name']})")
    return conf.space(spec["key"])


def sync_space_access(conf, seed, spec, people, roles):
    """Give each person exactly their role in the space; remove roles that open it to every user,
    and roles of people who should have no access. Admin and system accounts are left alone."""
    space = conf.space(spec["key"])
    names = {u["atlassian_account_id"]: n for n, u in people.items()}
    role_names = {v: k for k, v in roles.items()}
    want = {account_id(people, n): roles[seed["levels"][level]] for n, level in spec["access"].items()}
    current = conf.role_assignments(space["id"])
    changes = []
    for (ptype, pid), role in current.items():
        if (ptype == "ACCESS_CLASS" and pid in OPEN_TO_ALL) or (ptype == "USER" and pid in names and pid not in want):
            changes.append(({"principalType": ptype, "principalId": pid}, None))
    for aid, role_id in want.items():
        if current.get(("USER", aid)) != role_id:
            changes.append(({"principalType": "USER", "principalId": aid}, role_id))
    if changes:
        conf.api.request("POST", f"/wiki/api/v2/spaces/{space['id']}/role-assignments",
                         payload=[{"principal": p, "roleId": r} for p, r in changes])
    for p, r in changes:
        who = names.get(p["principalId"], p["principalId"])
        print(f"  {spec['key']}: {who} -> {role_names.get(r, 'no access')}")
    print(f"{spec['key']}: {len(changes)} change(s)")


def cmd_setup(conf, seed, people, args):
    roles = conf.roles()
    for spec in seed["spaces"]:
        ensure_space(conf, spec)
        sync_space_access(conf, seed, spec, people, roles)


# pages

def find_page(conf, space_id, title):
    return next((p for p in conf.pages(space_id) if p["title"] == title), None)


def page_body(conf, page_id):
    page = conf.api.request("GET", f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})
    return page, page.get("body", {}).get("storage", {}).get("value", "")


def write_page(conf, client, space, item, existing):
    body = storage(item["body"])
    if existing:
        current, value = page_body(conf, existing["id"])
        if current["title"] == item["title"] and storage_to_text(value) == storage_to_text(body):
            return existing["id"], "unchanged"
        client.request("PUT", f"/wiki/api/v2/pages/{existing['id']}", payload={
            "id": existing["id"], "status": "current", "title": item["title"],
            "body": {"representation": "storage", "value": body},
            "version": {"number": current["version"]["number"] + 1, "message": "Demo content"},
        })
        return existing["id"], "updated"
    created = client.request("POST", "/wiki/api/v2/pages", payload={
        "spaceId": space["id"], "status": "current", "title": item["title"], "parentId": space["homepageId"],
        "body": {"representation": "storage", "value": body},
    })
    return created["id"], "created"


def sync_comments(conf, clients, page_id, comments):
    """Make the page's comment thread match the seed, each comment posted by its author."""
    existing = conf.get_all(f"/wiki/api/v2/pages/{page_id}/footer-comments", {"body-format": "storage"})
    have = [storage_to_text(c.get("body", {}).get("storage", {}).get("value")) for c in existing]
    want = [storage_to_text(storage(c["text"])) for c in comments]
    if have == want:
        return 0
    for c in existing:
        conf.api.request("DELETE", f"/wiki/api/v2/footer-comments/{c['id']}")
    for c in comments:
        client = clients.get(c["author"]) or conf.api
        text = c["text"] if clients.get(c["author"]) else f"{c['author']} ({now_sgt()}): {c['text']}"
        client.request("POST", "/wiki/api/v2/footer-comments", payload={
            "pageId": page_id, "body": {"representation": "storage", "value": storage(text)}})
    return len(comments)


def cmd_seed(conf, seed, people, args):
    names = {p["author"] for p in seed["pages"]} | {c["author"] for p in seed["pages"] for c in p.get("comments", [])}
    clients = author_clients(conf.api, people, names, allow_fallback=args.fallback_comments)
    spaces = {s["key"]: conf.space(s["key"]) for s in seed["spaces"]}
    for t in seed["trash"]:
        page = find_page(conf, spaces[t["space"]]["id"], t["title"])
        if page:
            conf.api.request("DELETE", f"/wiki/api/v2/pages/{page['id']}")  # to the trash; restorable for 30 days
            print(f"Moved to trash: {t['space']}: {t['title']}")
    for item in seed["pages"]:
        space = spaces[item["space"]]
        client = clients.get(item["author"]) or conf.api
        existing = ({"id": space["homepageId"]} if item.get("home")
                    else find_page(conf, space["id"], item["title"]))
        page_id, what = write_page(conf, client, space, item, existing)
        posted = sync_comments(conf, clients, page_id, item.get("comments", []))
        print(f"{what.capitalize()}: {item['space']}: {item['title']} (by {item['author']})"
              + (f", {posted} comment(s) posted" if posted else ""))


# step 6: the restricted incident report

def report_pages(conf, space_id, title):
    """The report in any state: current, or in the trash (where its title still blocks a new page)."""
    return [p for status in ("current", "trashed")
            for p in conf.api.request("GET", "/wiki/api/v2/pages",
                                      {"space-id": space_id, "title": title, "status": status}).get("results", [])]


def restrict(client, page_id, accounts):
    """Only these accounts may view or edit the page."""
    users = [{"type": "known", "accountId": a} for a in accounts]
    client.request("PUT", f"/wiki/rest/api/content/{page_id}/restriction", payload=[
        {"operation": op, "restrictions": {"user": users, "group": []}} for op in ("read", "update")])


def cmd_incident_report(conf, seed, people, args):
    """Publish the incident report as its author and restrict it to the readers; --remove deletes it for good."""
    spec = seed["incident_report"]
    space = conf.space(spec["space"])
    found = report_pages(conf, space["id"], spec["title"])
    if args.remove:
        for page in found:
            if page["status"] == "current":
                conf.api.request("DELETE", f"/wiki/api/v2/pages/{page['id']}")
            conf.api.request("DELETE", f"/wiki/api/v2/pages/{page['id']}", {"purge": "true"})
        print(f"Deleted the incident report for good ({len(found)} page(s))" if found else "No incident report to remove")
        return

    readers = [account_id(people, n) for n in spec["readers"]]
    current = next((p for p in found if p["status"] == "current"), None)
    for page in found:
        if page["status"] == "trashed":  # a trashed copy would block the title
            conf.api.request("DELETE", f"/wiki/api/v2/pages/{page['id']}", {"purge": "true"})
    if current:
        restrict(conf.api, current["id"], readers)
        print(f"Already published: {spec['space']}: {spec['title']}; restrictions checked (page {current['id']})")
        page_id = current["id"]
    else:
        author = author_clients(conf.api, people, {spec["author"]})[spec["author"]]
        body = storage(spec["body"].replace("{date}", now_sgt().split()[0]))
        page_id = author.request("POST", "/wiki/api/v2/pages", payload={
            "spaceId": space["id"], "status": "current", "title": spec["title"], "parentId": space["homepageId"],
            "body": {"representation": "storage", "value": body},
        })["id"]
        try:
            restrict(author, page_id, readers)  # the author restricts their own page
            by = spec["author"]
        except RuntimeError:
            restrict(conf.api, page_id, readers)
            by = "the API account"
        # the page ID lets the web console index the page at once, before Confluence's search lists it
        print(f"{spec['author']} published {spec['space']}: {spec['title']}; restricted by {by} to "
              f"{', '.join(spec['readers'])} (page {page_id})")
    can = [n for n, u in people.items() if u.get("atlassian_account_id") and conf.can_read(u["atlassian_account_id"], page_id)]
    print(f"Confluence says these people can open it: {', '.join(can)}")
    if set(can) != set(spec["readers"]):
        raise RuntimeError(f"Expected exactly {', '.join(spec['readers'])} to be able to open the report")


# inspection

def cmd_check(conf, seed, people, args):
    names = {u["atlassian_account_id"]: n for n, u in people.items()}
    role_names = {v: k for k, v in conf.roles().items()}
    print(f"space role mode: {conf.api.request('GET', '/wiki/api/v2/space-role-mode').get('mode')}")
    for spec in seed["spaces"]:
        space = conf.space(spec["key"])
        if not space:
            print(f"{spec['key']}: not created")
            continue
        print(f"{spec['key']} ({space['name']}), {len(conf.pages(space['id']))} pages")
        for (ptype, pid), role in sorted(conf.role_assignments(space["id"]).items(), key=lambda x: str(x)):
            who = names.get(pid) or f"{ptype.lower()}:{pid[:24]}"
            print(f"  {who:<36} {role_names.get(role, role)}")


def cmd_access(conf, seed, people, args):
    """Who can read each space's home page, and each page, according to Confluence."""
    print(f"{'page':<62}" + "".join(f"{n:>9}" for n in people))
    for spec in seed["spaces"]:
        space = conf.space(spec["key"])
        if not space:
            continue
        for page in sorted(conf.pages(space["id"]), key=lambda p: p["title"]):
            label = f"{spec['key']}: {page['title']}"
            cells = "".join(f"{'✓' if conf.can_read(u['atlassian_account_id'], page['id']) else '·':>9}"
                            for u in people.values())
            print(f"{label[:61]:<62}{cells}")


COMMANDS = {"setup": cmd_setup, "seed": cmd_seed, "check": cmd_check, "access": cmd_access,
            "incident-report": cmd_incident_report}


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=list(COMMANDS))
    parser.add_argument("--fallback-comments", action="store_true",
                        help="seed: write as the API account (with the author's name) when a JIRA_TOKEN_<NAME> is missing")
    parser.add_argument("--remove", action="store_true", help="incident-report: delete it for good (rehearsal reset)")
    args = parser.parse_args()
    COMMANDS[args.command](Confluence(Jira()), load_seed(), load_people(), args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

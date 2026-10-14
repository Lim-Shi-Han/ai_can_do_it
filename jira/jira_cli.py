#!/usr/bin/env python3
"""Set up, seed, and inspect the hackathon Jira projects (PAY, ACC, FIN) using REST API v3."""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed_issues.json"
MANIFEST = ROOT / "issue_manifest.json"
IDENTITIES = Path(os.environ.get("IDENTITIES_FILE") or ROOT.parent / "main_workflow" / "identities.json")
DEFAULT_SITE = "https://hackathontencent.atlassian.net"
ENV_KEYS = {"JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"}
SGT = timezone(timedelta(hours=8))
TEMPLATES = [
    "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
    "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic",
]
OLD_PERMISSION_SCHEMES = {"PAY permission scheme"}  # earlier name; renamed on the next setup
MANAGED_ROLES = ("Administrators", "Member", "Viewer", "Security")
RESERVED_PROPERTY = "demo-reserved-through"
ISSUE_FIELDS = "summary,status,assignee,duedate,labels,issuelinks,description,comment,updated,project,security"
BLOCKS = {"paragraph", "heading", "listItem", "codeBlock", "blockquote", "rule", "tableRow"}
# a comment the API account posted for someone without a token: "Name (2026-10-16 14:05 SGT): text"
ON_BEHALF_RE = re.compile(r"^[A-Z][\w .'-]{0,40} \(\d{4}-\d{2}-\d{2}[^)]*\): ")


def load_local_env():
    """Read simple KEY=VALUE secrets without executing shell code."""
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in ENV_KEYS or key.startswith("JIRA_TOKEN_"):
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def load_seed():
    return json.loads(SEED.read_text(encoding="utf-8"))


def load_people():
    return {u["name"]: u for u in json.loads(IDENTITIES.read_text(encoding="utf-8"))["users"]}


def account_id(people, name):
    user = people.get(name)
    if not user:
        raise ValueError(f"No user {name!r} in {IDENTITIES}")
    if not user.get("atlassian_account_id"):
        raise ValueError(f"{name} has no atlassian_account_id in {IDENTITIES}")
    return user["atlassian_account_id"]


def project_of(issue_key):
    return issue_key.rsplit("-", 1)[0]


def adf(text):
    """Plain text to Atlassian Document Format. Blank lines separate blocks; lines starting with "- "
    become a bullet list, and a line before them ending in ":" stays a paragraph."""
    content = []
    for block in (b.strip() for b in text.split("\n\n") if b.strip()):
        lines = block.splitlines()
        bullets = [l[2:].strip() for l in lines if l.startswith("- ")]
        head = [l for l in lines if not l.startswith("- ")]
        if head:
            parts = []
            for line in head:
                parts += [{"type": "hardBreak"}] if parts else []
                parts.append({"type": "text", "text": line})
            content.append({"type": "paragraph", "content": parts})
        if bullets:
            content.append({"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": b}]}]}
                for b in bullets
            ]})
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node):
    def walk(n):
        if not isinstance(n, dict):
            return ""
        if n.get("type") == "text":
            return n.get("text", "")
        if n.get("type") == "hardBreak":
            return "\n"
        inner = "".join(walk(c) for c in n.get("content", []))
        if n.get("type") == "listItem":
            return "- " + inner.strip() + "\n"
        return inner + "\n" if n.get("type") in BLOCKS else inner

    return "\n".join(" ".join(line.split()) for line in walk(node).splitlines() if line.strip())


def parse_time(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z")


def utc(ts):
    return parse_time(ts).astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sgt(ts):
    return parse_time(ts).astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")


def now_sgt():
    return datetime.now(SGT).strftime("%Y-%m-%d %H:%M SGT")


class Jira:
    def __init__(self, email=None, token=None):
        email = email or os.environ.get("JIRA_EMAIL") or os.environ.get("ATLASSIAN_EMAIL")
        token = token or os.environ.get("JIRA_API_TOKEN") or os.environ.get("ATLASSIAN_API_TOKEN")
        if not email or not token:
            raise ValueError("Set JIRA_EMAIL and JIRA_API_TOKEN (or ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN) locally")
        self.site = (os.environ.get("JIRA_URL") or DEFAULT_SITE).rstrip("/")
        self.project_keys = [k.strip() for k in (os.environ.get("JIRA_PROJECT_KEY") or "PAY").split(",") if k.strip()]
        basic = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Accept": "application/json", "Authorization": f"Basic {basic}"}
        self._me = None

    def request(self, method, path, params=None, payload=None):
        if params:
            path += "?" + urllib.parse.urlencode(params, doseq=True)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            req = urllib.request.Request(self.site + path, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    retry_after = exc.headers.get("Retry-After", "")
                    time.sleep(int(retry_after) if retry_after.isdigit() else 2 ** attempt)
                    continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise RuntimeError(f"Jira API returned HTTP {exc.code} for {method} {path.split('?')[0]}: {detail}") from exc
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                # dropped connections are retried only for reads; retrying a create or comment could duplicate it
                read_only = method == "GET" or path.startswith("/rest/api/3/permissions/check")
                if read_only and attempt < 3:
                    time.sleep(1 + attempt)
                    continue
                raise

    def me(self):
        if self._me is None:
            self._me = self.request("GET", "/rest/api/3/myself")
        return self._me

    def search(self, jql, fields="summary", limit=1000):
        """JQL search with nextPageToken paging (the old /search endpoint is gone)."""
        params = {"jql": jql, "fields": fields, "maxResults": 100}
        issues, seen = [], set()
        while len(issues) < limit:
            response = self.request("GET", "/rest/api/3/search/jql", params)
            issues.extend(response.get("issues", []))
            token = response.get("nextPageToken")
            if response.get("isLast", True) or not token or token in seen:
                break
            seen.add(token)
            params["nextPageToken"] = token
        return issues[:limit]

    def issue(self, key, fields=ISSUE_FIELDS):
        return self.request("GET", f"/rest/api/3/issue/{key}", {"fields": fields})

    def issue_url(self, key):
        return f"{self.site}/browse/{key}"

    def project(self, key):
        try:
            return self.request("GET", f"/rest/api/3/project/{key}")
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def global_roles(self):
        return {r["name"]: r["id"] for r in self.request("GET", "/rest/api/3/role") if not r.get("scope")}

    def role_actors(self, key, role_id):
        return self.request("GET", f"/rest/api/3/project/{key}/role/{role_id}").get("actors", [])

    def role_users(self, key, role_id):
        return {a["actorUser"]["accountId"] for a in self.role_actors(key, role_id)
                if a.get("type") == "atlassian-user-role-actor"}

    def security_levels(self, key):
        response = self.request("GET", f"/rest/api/3/project/{key}/securitylevel")
        return {level["name"]: level["id"] for level in response.get("levels", [])}

    def _check(self, user, projects=(), issues=()):
        aid = user.get("atlassian_account_id")
        if not aid or not (projects or issues):
            return set(), set()
        grant = {"permissions": ["BROWSE_PROJECTS"]}
        if projects:
            grant["projects"] = [int(p) for p in projects]
        if issues:
            grant["issues"] = [int(i) for i in issues]
        response = self.request("POST", "/rest/api/3/permissions/check",
                                payload={"accountId": aid, "projectPermissions": [grant]})
        allowed_projects, allowed_issues = set(), set()
        for g in response.get("projectPermissions", []):
            allowed_projects |= {str(p) for p in g.get("projects", [])}
            allowed_issues |= {str(i) for i in g.get("issues", [])}
        return allowed_projects, allowed_issues

    def can_browse(self, user, issue_ids):
        """Issue IDs (as strings) the user may browse, decided by Jira itself. Never cached."""
        return self._check(user, issues=issue_ids)[1]

    def can_browse_projects(self, user, project_ids):
        return self._check(user, projects=project_ids)[0]

    def transition(self, key, status):
        current = self.issue(key, "status")["fields"]["status"]["name"]
        if current.lower() == status.lower():
            return False
        transitions = self.request("GET", f"/rest/api/3/issue/{key}/transitions")["transitions"]
        match = next((t for t in transitions if t["to"]["name"].lower() == status.lower()), None)
        if not match:
            names = sorted({t["to"]["name"] for t in transitions})
            raise RuntimeError(f"{key}: no transition to {status!r}; available: {names}")
        self.request("POST", f"/rest/api/3/issue/{key}/transitions", payload={"transition": {"id": match["id"]}})
        return True


def author_clients(api, people, names, allow_fallback=False):
    """A Jira client per person that posts as that person, from JIRA_TOKEN_<NAME> in .env.
    The API account's own persona uses the main client. None means: post on their behalf."""
    me = api.me()["accountId"]
    clients, missing = {}, []
    for name in sorted(set(names)):
        aid = account_id(people, name)
        token = os.environ.get(f"JIRA_TOKEN_{name.upper()}")
        if aid == me:
            clients[name] = api
        elif not token:
            clients[name] = None
            missing.append(f"JIRA_TOKEN_{name.upper()}")
        else:
            client = Jira(email=people[name].get("email"), token=token)
            if client.me()["accountId"] != aid:
                raise ValueError(f"JIRA_TOKEN_{name.upper()} belongs to a different account than {name}")
            clients[name] = client
    if missing and not allow_fallback:
        raise ValueError(f"Missing {', '.join(missing)} in .env; add them, or rerun with --fallback-comments "
                         "to post those comments from the API account with the author's name in the text")
    return clients


def post_comment(api, clients, key, author, text):
    client = clients.get(author)
    if client is None:
        api.request("POST", f"/rest/api/3/issue/{key}/comment", payload={"body": adf(f"{author} ({now_sgt()}): {text}")})
    else:
        client.request("POST", f"/rest/api/3/issue/{key}/comment", payload={"body": adf(text)})


def issue_text(api, issue):
    """Plain text for citations and the model, in the same layout as the stand-in Jira source.
    A comment the API account posted on someone's behalf already starts with their name and time."""
    f = issue["fields"]
    links = []
    for link in f.get("issuelinks") or []:
        if "outwardIssue" in link:
            links.append(f"{link['type']['outward']} {link['outwardIssue']['key']}")
        elif "inwardIssue" in link:
            links.append(f"{link['type']['inward']} {link['inwardIssue']['key']}")
    lines = [
        f"{issue['key']}: {f['summary']}",
        f"Status: {f['status']['name']}",
        f"Assignee: {(f.get('assignee') or {}).get('displayName', 'Unassigned')}",
        f"Due: {f.get('duedate') or 'none'}",
        f"Labels: {', '.join(f.get('labels') or []) or 'none'}",
    ]
    if links:
        lines.append(f"Links: {', '.join(links)}")
    description = adf_to_text(f.get("description"))
    if description:
        lines += ["", description]
    comments = (f.get("comment") or {}).get("comments", [])
    if comments:
        lines += ["", "Comments:"]
        me = api.me()["accountId"]
        for c in comments:
            body = adf_to_text(c.get("body"))
            if c.get("author", {}).get("accountId") == me and ON_BEHALF_RE.match(body):
                lines.append(f"- {body}")
            else:
                lines.append(f"- {c.get('author', {}).get('displayName', 'unknown')} ({sgt(c['created'])}): {body}")
    lines.append(f"\nLast updated {sgt(f['updated'])}.")
    return "\n".join(lines)


# setup

def ensure_roles(api):
    roles = api.global_roles()
    for name in MANAGED_ROLES:
        if name not in roles:
            created = api.request("POST", "/rest/api/3/role", payload={
                "name": name, "description": f"{name} role for the hackathon demo projects"})
            roles[name] = created["id"]
            print(f"Created project role {name} ({created['id']})")
    return roles


def required_grants(roles):
    admins, member, viewer, security = (str(roles[r]) for r in MANAGED_ROLES)
    return {
        ("BROWSE_PROJECTS", "projectRole", admins),
        ("BROWSE_PROJECTS", "projectRole", member),
        ("BROWSE_PROJECTS", "projectRole", viewer),  # Viewer can read, nothing else
        ("SET_ISSUE_SECURITY", "projectRole", admins),
        ("SET_ISSUE_SECURITY", "projectRole", security),
    }


def admins_like_members(grants, roles):
    """Administrators also get everything Members can do (create, comment, transition...)."""
    member, admins = str(roles["Member"]), str(roles["Administrators"])
    return {(perm, "projectRole", admins) for perm, htype, param in grants
            if htype == "projectRole" and param == member}


def ensure_permission_scheme(api, seed, roles):
    name = seed["permission_scheme"]
    description = "Default permissions, but only project roles get access (no application-wide access)."
    existing = api.request("GET", "/rest/api/3/permissionscheme")["permissionSchemes"]
    match = (next((s for s in existing if s["name"] == name), None)
             or next((s for s in existing if s["name"] in OLD_PERMISSION_SCHEMES), None))
    if match:
        if match["name"] != name:
            # no permissions list in the body, so the existing grants are kept
            api.request("PUT", f"/rest/api/3/permissionscheme/{match['id']}",
                        payload={"name": name, "description": description})
            print(f"Renamed permission scheme {match['name']!r} to {name!r}")
        full = api.request("GET", f"/rest/api/3/permissionscheme/{match['id']}", {"expand": "permissions"})
        have = {(p["permission"], p["holder"].get("type"), p["holder"].get("parameter") or "") for p in full["permissions"]}
        need = required_grants(roles) | admins_like_members(have, roles)
        for perm, htype, param in sorted(need - have):
            api.request("POST", f"/rest/api/3/permissionscheme/{match['id']}/permission",
                        payload={"permission": perm, "holder": {"type": htype, "parameter": param}})
            print(f"Added {perm} for role {param} to {name}")
        return match["id"]
    default = api.request("GET", "/rest/api/3/permissionscheme/0", {"expand": "permissions"})
    known = {k for k, v in api.request("GET", "/rest/api/3/permissions")["permissions"].items() if v.get("type") == "PROJECT"}
    member = str(roles["Member"])
    grants = set()
    for p in default["permissions"]:
        if p["permission"] not in known:
            continue  # internal grants such as VIEW_PROJECTS cannot be set through the API
        holder = p["holder"]
        htype, param = holder.get("type"), holder.get("parameter") or ""
        if htype in ("applicationRole", "anyone"):
            # "anyone with Jira access" becomes project members only, so access follows project roles
            htype, param = "projectRole", member
        grants.add((p["permission"], htype, param))
    grants |= required_grants(roles)
    grants |= admins_like_members(grants, roles)
    created = api.request("POST", "/rest/api/3/permissionscheme", payload={
        "name": name, "description": description,
        "permissions": [
            {"permission": perm, "holder": {"type": htype, **({"parameter": param} if param else {})}}
            for perm, htype, param in sorted(grants)
        ],
    })
    print(f"Created permission scheme {name} ({created['id']})")
    return created["id"]


def ensure_security_scheme(api, seed, roles):
    name, level = seed["issue_security_scheme"], seed["security_level"]
    existing = api.request("GET", "/rest/api/3/issuesecurityschemes").get("issueSecuritySchemes", [])
    match = next((s for s in existing if s["name"] == name), None)
    if match:
        return match["id"]
    created = api.request("POST", "/rest/api/3/issuesecurityschemes", payload={
        "name": name,
        "description": "Issue-level restriction for security-sensitive tickets.",
        "levels": [{
            "name": level, "description": "Visible only to the Security project role.", "isDefault": False,
            "members": [{"type": "projectrole", "parameter": str(roles["Security"])}],  # lowercase here, unlike permission schemes
        }],
    })
    print(f"Created issue security scheme {name} ({created['id']}) with level {level}")
    return created["id"]


def create_project(api, project, permission_scheme, security_scheme):
    last_error = None
    for template in TEMPLATES:
        payload = {
            "key": project["key"], "name": project["name"], "description": project["description"],
            "projectTypeKey": "software", "projectTemplateKey": template,
            "leadAccountId": api.me()["accountId"], "assigneeType": "UNASSIGNED",
            "permissionScheme": int(permission_scheme),
        }
        if security_scheme:
            payload["issueSecurityScheme"] = int(security_scheme)
        for attempt in range(6):
            try:
                api.request("POST", "/rest/api/3/project", payload=payload)
            except RuntimeError as exc:
                last_error = exc
                if "already" in str(exc).lower() and attempt < 5:
                    time.sleep(10)  # a just-deleted project can hold its key for a few seconds
                    continue
                print(f"Template {template.rsplit(':', 1)[-1]} rejected: {str(exc)[:200]}")
                break
            print(f"Created company-managed project {project['key']} ({project['name']})")
            return
    raise RuntimeError(f"Could not create project {project['key']}: {last_error}")


def ensure_screen_fields(api, key, fields):
    screens = api.request("GET", "/rest/api/3/screens", {"queryString": f"{key}:", "maxResults": 100}).get("values", [])
    for screen in screens:
        if not screen["name"].startswith(f"{key}:"):
            continue
        tabs = api.request("GET", f"/rest/api/3/screens/{screen['id']}/tabs")
        if not tabs:
            continue
        present = {f["id"] for tab in tabs
                   for f in api.request("GET", f"/rest/api/3/screens/{screen['id']}/tabs/{tab['id']}/fields")}
        for field in fields:
            if field not in present:
                api.request("POST", f"/rest/api/3/screens/{screen['id']}/tabs/{tabs[0]['id']}/fields",
                            payload={"fieldId": field})
                print(f"Added {field} to screen {screen['name']!r}")


def sync_roles(api, project, people, roles):
    """Make each managed role in the project hold exactly the seeded users; roles not listed end up empty."""
    key, changes = project["key"], 0
    for role_name in MANAGED_ROLES:
        role_id = roles[role_name]
        want = {account_id(people, n) for n in project["roles"].get(role_name, [])}
        actors = api.role_actors(key, role_id)
        for a in actors:
            if a.get("type") == "atlassian-group-role-actor":
                group_id = a.get("actorGroup", {}).get("groupId")
                params = {"groupId": group_id} if group_id else {"group": a.get("name")}
                api.request("DELETE", f"/rest/api/3/project/{key}/role/{role_id}", params)
                changes += 1
        have = {a["actorUser"]["accountId"] for a in actors if a.get("type") == "atlassian-user-role-actor"}
        if want - have:
            api.request("POST", f"/rest/api/3/project/{key}/role/{role_id}", payload={"user": sorted(want - have)})
            changes += len(want - have)
        for aid in have - want:
            api.request("DELETE", f"/rest/api/3/project/{key}/role/{role_id}", {"user": aid})
            changes += 1
    return changes


def cmd_setup(api, seed, people, args):
    roles = ensure_roles(api)
    permission_scheme = ensure_permission_scheme(api, seed, roles)
    security_scheme = ensure_security_scheme(api, seed, roles)
    for project in seed["projects"]:
        key = project["key"]
        existing = api.project(key)
        if existing and existing.get("style") == "next-gen":
            if not args.delete_team_managed:
                raise ValueError(f"{key} is a team-managed project; rerun with --delete-team-managed to replace it")
            if api.search(f"project = {key}", "summary", limit=1):
                raise RuntimeError(f"Refusing to delete {key}: it has issues")
            delete_project(api, key)
            existing = None
        if not existing:
            create_project(api, project, permission_scheme, security_scheme if project["issue_security"] else None)
        ensure_screen_fields(api, key, ("duedate", "security") if project["issue_security"] else ("duedate",))
        print(f"{key}: {sync_roles(api, project, people, roles)} role change(s)")


def delete_project(api, key):
    api.request("DELETE", f"/rest/api/3/project/{key}", {"enableUndo": "false"})
    for _ in range(45):
        if api.project(key) is None:
            print(f"Deleted project {key} permanently")
            return
        time.sleep(2)
    raise RuntimeError(f"Project {key} still exists 90 s after deletion")


# seed

def reserved_through(api, key):
    try:
        return api.request("GET", f"/rest/api/3/project/{key}/properties/{RESERVED_PROPERTY}")["value"]["through"]
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return 0
        raise


def reserve_keys(api, key, through):
    """Create and delete placeholder issues so the next new issue in the project gets number through + 1.
    A project property records it, so running seed again never uses up more keys."""
    if not through or reserved_through(api, key) >= through:
        return
    fields = {"project": {"key": key}, "issuetype": {"name": "Task"}, "summary": "Reserved key"}
    first = api.request("POST", "/rest/api/3/issue", payload={"fields": fields})
    keys = [first["key"]]
    number = int(first["key"].rsplit("-", 1)[1])
    try:
        if number > through:
            raise RuntimeError(f"Next key is already {first['key']}; cannot reserve keys up to {key}-{through}")
        remaining = through - number
        while remaining > 0:
            batch = min(50, remaining)
            response = api.request("POST", "/rest/api/3/issue/bulk",
                                   payload={"issueUpdates": [{"fields": fields} for _ in range(batch)]})
            if response.get("errors"):
                raise RuntimeError(f"Bulk create failed: {json.dumps(response['errors'])[:300]}")
            keys += [i["key"] for i in response["issues"]]
            remaining -= batch
        last = max(int(k.rsplit("-", 1)[1]) for k in keys)
        if last != through:
            raise RuntimeError(f"Reserved up to {key}-{last}, expected {key}-{through}")
    finally:
        for k in keys:
            api.request("DELETE", f"/rest/api/3/issue/{k}")
    api.request("PUT", f"/rest/api/3/project/{key}/properties/{RESERVED_PROPERTY}", payload={"through": through})
    print(f"{key}: reserved and deleted {len(keys)} placeholder issues; the next issue is {key}-{through + 1}")


def create_issue(api, item, people, levels, clients):
    key = project_of(item["key"])
    fields = {
        "project": {"key": key},
        "issuetype": {"name": item["type"]},
        "summary": item["summary"],
        "description": adf(item["description"]),
        "labels": item["labels"],
        "duedate": item["due"],
    }
    if item.get("reporter"):
        fields["reporter"] = {"accountId": account_id(people, item["reporter"])}
    if item.get("assignee"):
        fields["assignee"] = {"accountId": account_id(people, item["assignee"])}
    if item.get("security"):
        fields["security"] = {"id": levels[key][item.get("security_level", "Security")]}
    created = api.request("POST", "/rest/api/3/issue", payload={"fields": fields})
    if created["key"] != item["key"]:
        raise RuntimeError(f"Expected {item['key']} but Jira assigned {created['key']}; stopping")
    api.transition(created["key"], item["status"])
    for comment in item["comments"]:
        post_comment(api, clients, created["key"], comment["author"], comment["text"])
    print(f"Created {created['key']} [{item['status']}] {item['summary']}")
    return created["key"]


def update_issue(api, key, item, people, clients):
    """Bring an existing seed ticket in line with the seed: fields, status, and the comment thread."""
    fields = {
        "description": adf(item["description"]),
        "labels": item["labels"],
        "duedate": item["due"],
        "assignee": {"accountId": account_id(people, item["assignee"])} if item.get("assignee") else None,
    }
    if item.get("reporter"):
        fields["reporter"] = {"accountId": account_id(people, item["reporter"])}
    api.request("PUT", f"/rest/api/3/issue/{key}", payload={"fields": fields})
    current_type = api.issue(key, "issuetype")["fields"]["issuetype"]["name"]
    if current_type != item["type"]:
        try:
            api.request("PUT", f"/rest/api/3/issue/{key}", payload={"fields": {"issuetype": {"name": item["type"]}}})
        except RuntimeError as exc:
            print(f"{key}: could not change type to {item['type']}: {str(exc)[:150]}")
    api.transition(key, item["status"])
    comments = (api.issue(key, "comment")["fields"].get("comment") or {}).get("comments", [])
    have = [ON_BEHALF_RE.sub("", adf_to_text(c.get("body"))) for c in comments]
    want = [c["text"] for c in item["comments"]]
    if have != want:
        for c in comments:
            api.request("DELETE", f"/rest/api/3/issue/{key}/comment/{c['id']}")
        for comment in item["comments"]:
            post_comment(api, clients, key, comment["author"], comment["text"])
    print(f"Updated {key} [{item['status']}] {item['summary']}" + ("" if have == want else f" ({len(want)} comment(s) re-posted)"))


def add_links(api, seed, existing):
    for item in seed["issues"]:
        key = existing.get(item["summary"])
        for link in item.get("links", []):
            current = api.issue(key, "issuelinks")["fields"].get("issuelinks") or []
            linked = {(l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key") for l in current}
            if link["to"] in linked:
                continue
            api.request("POST", "/rest/api/3/issueLink", payload={
                "type": {"name": link["type"]}, "inwardIssue": {"key": key}, "outwardIssue": {"key": link["to"]}})
            print(f"Linked {key} {link['type'].lower()} {link['to']}")


def project_keys(seed):
    return [p["key"] for p in seed["projects"]]


def save_manifest(api, seed):
    issues = api.search(f"project in ({', '.join(project_keys(seed))}) ORDER BY key ASC",
                        "summary,status,updated,labels,security")
    data = {
        "source": "jira",
        "site": api.site,
        "projects": project_keys(seed),
        "issues": [{
            "key": i["key"], "id": i["id"], "summary": i["fields"]["summary"],
            "status": i["fields"]["status"]["name"], "labels": i["fields"].get("labels", []),
            "restricted": bool(i["fields"].get("security")),
            "url": api.issue_url(i["key"]), "updated_at": utc(i["fields"]["updated"]),
        } for i in issues],
    }
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def cmd_seed(api, seed, people, args):
    authors = [c["author"] for item in seed["issues"] for c in item["comments"]]
    clients = author_clients(api, people, authors, allow_fallback=args.fallback_comments)
    keys = project_keys(seed)
    existing = {i["fields"]["summary"]: i["key"]
                for i in api.search(f"project in ({', '.join(keys)})", "summary")}
    levels = {p["key"]: api.security_levels(p["key"]) for p in seed["projects"] if p["issue_security"]}
    for project in seed["projects"]:
        reserve_keys(api, project["key"], project.get("reserve_through"))
    for item in seed["issues"]:
        if item["summary"] in existing:
            update_issue(api, existing[item["summary"]], item, people, clients)
            continue
        existing[item["summary"]] = create_issue(api, item, people, levels, clients)
    add_links(api, seed, existing)
    cmd_list(api, seed, people, args)


def cmd_rebuild(api, seed, people, args):
    """Delete and recreate every demo project with only the seed tickets, so the live demo's
    tickets get the same keys again. Jira never reuses a key, so this is the only way to reset them."""
    keys = [k.strip() for k in args.only.split(",")] if args.only else project_keys(seed)
    unknown = set(keys) - set(project_keys(seed))
    if unknown:
        raise ValueError(f"Not a demo project: {', '.join(sorted(unknown))}")
    if not args.yes:
        raise ValueError(f"rebuild permanently deletes {', '.join(keys)} and every ticket in them; rerun with --yes")
    for key in keys:
        if api.project(key):
            delete_project(api, key)
    cmd_setup(api, seed, people, args)
    cmd_seed(api, seed, people, args)


# inspection and demo controls

def cmd_check(api, seed, people, args):
    me = api.me()
    names = {u.get("atlassian_account_id"): n for n, u in people.items()}
    print(f"Connected to {api.site} as {me['displayName']} (persona {names.get(me['accountId'], 'none')})")
    for app in api.request("GET", "/rest/api/3/instance/license").get("applications", []):
        print(f"Plan: {app.get('id')} {app.get('plan')}")
    role_names = {str(v): k for k, v in api.global_roles().items()}
    for p in seed["projects"]:
        key = p["key"]
        project = api.project(key)
        if not project:
            print(f"Project {key}: not found")
            continue
        style = "company-managed" if project.get("style") == "classic" else "team-managed"
        print(f"Project {key} ({project['name']}): {style}")
        roles = {r: url.rstrip("/").rsplit("/", 1)[-1]
                 for r, url in api.request("GET", f"/rest/api/3/project/{key}/role").items()}
        for name in MANAGED_ROLES:
            if name in roles:
                members = sorted(names.get(a, a) for a in api.role_users(key, roles[name]))
                print(f"  role {name}: {', '.join(members) or 'nobody'}")
        scheme = api.request("GET", f"/rest/api/3/project/{key}/permissionscheme")
        full = api.request("GET", f"/rest/api/3/permissionscheme/{scheme['id']}", {"expand": "permissions"})
        browse = sorted(
            f"{p2['holder']['type']}:{role_names.get(p2['holder'].get('parameter', ''), p2['holder'].get('parameter', ''))}"
            for p2 in full["permissions"] if p2["permission"] == "BROWSE_PROJECTS")
        print(f"  permission scheme {scheme['name']!r}: browse -> {', '.join(browse)}")
        if p["issue_security"]:
            print(f"  security levels: {', '.join(api.security_levels(key)) or 'none'}")
        statuses = sorted({s["name"] for t in api.request("GET", f"/rest/api/3/project/{key}/statuses")
                           for s in t.get("statuses", [])})
        print(f"  statuses: {', '.join(statuses)}")
        print(f"  issues: {len(api.search(f'project = {key}', 'summary'))}; "
              f"keys reserved through {key}-{reserved_through(api, key)}")


def cmd_list(api, seed, people, args):
    manifest = save_manifest(api, seed)
    for i in manifest["issues"]:
        lock = " [restricted]" if i["restricted"] else ""
        print(f"{i['key']:<8} {i['status']:<12} {i['summary']}{lock}")
    print(f"Manifest saved to {MANIFEST}")


def cmd_read(api, seed, people, args):
    if not args.target:
        raise ValueError("read requires an issue key")
    issue = api.issue(args.target[0])
    print(json.dumps({
        "key": issue["key"], "id": issue["id"], "title": f"{issue['key']} {issue['fields']['summary']}",
        "url": api.issue_url(issue["key"]), "version": utc(issue["fields"]["updated"]),
        "updated_at": utc(issue["fields"]["updated"]), "container": issue["fields"]["project"]["key"],
        "text": issue_text(api, issue),
    }, indent=2, ensure_ascii=False))


def cmd_access(api, seed, people, args):
    keys = project_keys(seed)
    projects = {k: api.project(k) for k in keys}
    project_ids = [p["id"] for p in projects.values() if p]
    header = "".join(f"{n:>9}" for n in people)
    allowed = {name: api.can_browse_projects(user, project_ids) for name, user in people.items()}
    print(f"{'project':<62}{header}")
    for key, p in projects.items():
        if p:
            print(f"{(key + ' ' + p['name'])[:61]:<62}" + "".join(f"{'✓' if p['id'] in allowed[n] else '·':>9}" for n in people))
    issues = api.search(f"project in ({', '.join(keys)}) ORDER BY key ASC", "summary")
    if not issues:
        return
    ids = [i["id"] for i in issues]
    allowed = {name: api.can_browse(user, ids) for name, user in people.items()}
    print(f"\n{'issue':<62}{header}")
    for i in issues:
        label = f"{i['key']} {i['fields']['summary']}"
        print(f"{label[:61]:<62}" + "".join(f"{'✓' if i['id'] in allowed[n] else '·':>9}" for n in people))
    if args.cross_check:
        mismatches = 0
        for i in issues:
            for name, user in people.items():
                aid = user.get("atlassian_account_id")
                if not aid:
                    continue
                found = api.request("GET", "/rest/api/3/user/viewissue/search",
                                    {"issueKey": i["key"], "accountId": aid, "maxResults": 1})
                if bool(found) != (i["id"] in allowed[name]):
                    mismatches += 1
                    print(f"MISMATCH {i['key']} {name}: permission check says "
                          f"{i['id'] in allowed[name]}, browse-user search says {bool(found)}")
        print(f"Cross-check: {mismatches} mismatch(es)")


def change_access(api, seed, people, args, grant):
    targets = seed["targets"]
    if len(args.target) != 2 or args.target[1] not in targets:
        raise ValueError(f"usage: {'grant' if grant else 'revoke'} USER TARGET, where TARGET is one of {', '.join(targets)}")
    name, target = args.target
    key, role = targets[target]
    role_id = api.global_roles()[role]
    aid = account_id(people, name)
    where = f"Jira project {key}" if role == "Member" else f"Jira {key} {role.lower()} level"
    members = api.role_users(key, role_id)
    if grant == (aid in members):
        print(f"No change: {name} {'already has' if grant else 'does not have'} access to {where}")
        return
    if grant:
        api.request("POST", f"/rest/api/3/project/{key}/role/{role_id}", payload={"user": [aid]})
    else:
        api.request("DELETE", f"/rest/api/3/project/{key}/role/{role_id}", {"user": aid})
    print(f"{'Granted' if grant else 'Revoked'} {name} {'on' if grant else 'from'} {where}")


def cmd_set_status(api, seed, people, args):
    if len(args.target) != 2:
        raise ValueError("usage: set-status KEY STATUS [--comment TEXT] [--author NAME]")
    key, status = args.target
    api.transition(key, status)
    if args.comment:
        clients = author_clients(api, people, [args.author], allow_fallback=True)
        post_comment(api, clients, key, args.author, args.comment)
    print(f"{key} is now {status}")


def cmd_reset(api, seed, people, args):
    """Restore role memberships and the seed tickets. Tickets created during a demo stay; use rebuild for those."""
    roles = api.global_roles()
    role_changes = sum(sync_roles(api, p, people, roles) for p in seed["projects"])
    keys = {i["fields"]["summary"]: i["key"]
            for i in api.search(f"project in ({', '.join(project_keys(seed))})", "summary")}
    status_changes = removed = 0
    for item in seed["issues"]:
        key = keys.get(item["summary"])
        if not key:
            continue
        status_changes += api.transition(key, item["status"])
        seeded = {c["text"] for c in item["comments"]}
        for c in (api.issue(key, "comment")["fields"].get("comment") or {}).get("comments", []):
            body = adf_to_text(c.get("body"))
            if body not in seeded and ON_BEHALF_RE.sub("", body) not in seeded:
                api.request("DELETE", f"/rest/api/3/issue/{key}/comment/{c['id']}")
                removed += 1
    print(f"Jira reset to seed: {role_changes} role change(s), {status_changes} status change(s), "
          f"{removed} comment(s) removed")


COMMANDS = {
    "check": cmd_check, "setup": cmd_setup, "seed": cmd_seed, "rebuild": cmd_rebuild, "list": cmd_list,
    "read": cmd_read, "access": cmd_access, "set-status": cmd_set_status, "reset": cmd_reset,
    "grant": lambda *a: change_access(*a, grant=True), "revoke": lambda *a: change_access(*a, grant=False),
}


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=list(COMMANDS))
    parser.add_argument("target", nargs="*", help="issue key for read; USER TARGET for grant/revoke; KEY STATUS for set-status")
    parser.add_argument("--delete-team-managed", action="store_true", help="setup: replace an empty team-managed project")
    parser.add_argument("--yes", action="store_true", help="rebuild: confirm deleting and recreating the projects")
    parser.add_argument("--only", help="rebuild: comma-separated project keys to rebuild (default: all demo projects)")
    parser.add_argument("--cross-check", action="store_true", help="access: compare with Jira's browse-user search")
    parser.add_argument("--fallback-comments", action="store_true",
                        help="seed: post comments for people without a JIRA_TOKEN_<NAME> from the API account")
    parser.add_argument("--comment", help="set-status: comment to add")
    parser.add_argument("--author", default="ShiHan", help="set-status: name shown in the comment")
    args = parser.parse_args()
    COMMANDS[args.command](Jira(), load_seed(), load_people(), args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

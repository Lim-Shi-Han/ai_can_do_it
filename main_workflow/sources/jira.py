import math
import re
from datetime import datetime, timezone

from jira.jira_cli import ISSUE_FIELDS, Jira, issue_text, load_local_env, utc

from .base import Candidate, Doc, keywords

KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


class JiraSource:
    name = "jira"

    def __init__(self):
        load_local_env()
        self.api = Jira()
        self.projects = self.api.project_keys  # JIRA_PROJECT_KEY, e.g. PAY,ACC,FIN

    def _scope(self):
        return f"project in ({', '.join(self.projects)})"

    def _candidate(self, issue):
        f = issue["fields"]
        return Candidate(self.name, issue["key"], f"{issue['key']} {f['summary']}", f["project"]["key"], utc(f["updated"]))

    def _search(self, jql, limit):
        return [self._candidate(i) for i in self.api.search(jql, "summary,updated,project", limit)]

    def search(self, query, incident_id=None, limit=10):
        found = []
        # ticket keys named in the question, e.g. "PAY-100: what changed?", are looked up directly
        for key in dict.fromkeys(KEY_RE.findall(query)):
            if key.rsplit("-", 1)[0] in self.projects:
                try:
                    found.append(self._candidate(self.api.issue(key, "summary,updated,project")))
                except RuntimeError:
                    pass
        terms = [f'text ~ "{t.replace("-", " ")}"' for t in keywords(query)]
        if incident_id:
            terms[:0] = [f'labels = "{incident_id}"', f'text ~ "{incident_id.replace("-", " ")}"']
        if terms and len(found) < limit:
            seen = {c.doc_id for c in found}
            jql = f"{self._scope()} AND ({' OR '.join(terms)}) ORDER BY updated DESC"
            found += [c for c in self._search(jql, limit) if c.doc_id not in seen]
        return found[:limit]

    def can_access(self, user, doc_id):
        """Live check, never cached. Project access comes from Jira's project-role check, which reflects role
        changes immediately. A ticket with a security level must also pass Jira's issue-level check, the only
        endpoint that applies issue security (its role data can lag, so it is used for nothing else)."""
        account_id = user.get("atlassian_account_id")
        project = doc_id.rsplit("-", 1)[0]  # the key names the project, so people outside it cost one call
        if not account_id or project not in self.projects:
            return False
        members = self.api.request("GET", "/rest/api/3/user/permission/search", {
            "accountId": account_id, "permissions": "BROWSE_PROJECTS", "projectKey": project, "maxResults": 1})
        if not any(u.get("accountId") == account_id for u in members):
            return False
        issue = self.api.issue(doc_id, "project,security")
        if issue["fields"]["project"]["key"] != project:
            return False
        if issue["fields"].get("security"):
            return issue["id"] in self.api.can_browse(user, [issue["id"]])
        return True

    def fetch(self, doc_id):
        issue = self.api.issue(doc_id, ISSUE_FIELDS)
        f = issue["fields"]
        updated = utc(f["updated"])
        return Doc(
            source=self.name,
            doc_id=issue["key"],
            title=f"{issue['key']} {f['summary']}",
            url=self.api.issue_url(issue["key"]),
            version=updated,  # Jira has no version number; "updated" changes on every edit, transition, and comment
            updated_at=updated,
            text=issue_text(self.api, issue),
            container=f["project"]["key"],
        )

    def changes_since(self, ts):
        jql = self._scope()
        if ts:
            # relative minutes avoid JQL's dependence on the account's profile timezone
            since = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            minutes = math.ceil((datetime.now(timezone.utc) - since).total_seconds() / 60) + 1
            jql += f' AND updated >= "-{minutes}m"'
        return self._search(jql + " ORDER BY updated DESC", 1000)

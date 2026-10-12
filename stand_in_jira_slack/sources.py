"""Stand-in Jira and Slack sources backed by state.json, using the same interface as the real ones."""

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from main_workflow.sources.base import Candidate, Doc, keywords

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed.json"
STATE = Path(os.environ.get("STAND_IN_STATE") or ROOT / "state.json")
SGT = timezone(timedelta(hours=8))


def load_state():
    if not STATE.exists():
        shutil.copyfile(SEED, STATE)
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATE)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sgt(ts):
    if "T" in ts:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = datetime.fromtimestamp(float(ts), timezone.utc)
    return dt.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")


def matches(text, query, incident_id):
    terms = keywords(query)
    if incident_id:
        terms.insert(0, incident_id.lower())
    text = text.lower()
    return sum(1 for t in terms if t in text)


class _FixtureSource:
    name = ""

    def _items(self, state):
        raise NotImplementedError

    def _doc(self, state, item):
        raise NotImplementedError

    def _find(self, state, doc_id):
        for item in self._items(state):
            if self._id(item) == doc_id:
                return item
        raise RuntimeError(f"{self.name}: {doc_id} not found")

    def search(self, query, incident_id=None, limit=10):
        state = load_state()
        scored = []
        for item in self._items(state):
            doc = self._doc(state, item)
            score = matches(doc.title + "\n" + doc.text, query, incident_id)
            if score:
                scored.append((score, Candidate(self.name, doc.doc_id, doc.title, doc.container, doc.version)))
        scored.sort(key=lambda pair: -pair[0])
        return [c for _, c in scored[:limit]]

    def fetch(self, doc_id):
        state = load_state()
        return self._doc(state, self._find(state, doc_id))

    def changes_since(self, ts):
        state = load_state()
        out = []
        for item in self._items(state):
            if ts is None or item["updated_at"] > ts:
                doc = self._doc(state, item)
                out.append(Candidate(self.name, doc.doc_id, doc.title, doc.container, doc.version))
        return out


class JiraFixtureSource(_FixtureSource):
    name = "jira-fixture"

    def _items(self, state):
        return state["jira"]["issues"]

    def _id(self, item):
        return item["key"]

    def _doc(self, state, issue):
        lines = [
            f"{issue['key']}: {issue['summary']}",
            f"Status: {issue['status']}",
            f"Assignee: {issue['assignee']}",
            f"Due: {issue['due']}",
            f"Labels: {', '.join(issue['labels'])}",
        ]
        if issue.get("links"):
            lines.append(f"Links: {', '.join(issue['links'])}")
        lines += ["", issue["description"]]
        if issue["comments"]:
            lines += ["", "Comments:"]
            lines += [f"- {c['author']} ({sgt(c['at'])}): {c['text']}" for c in issue["comments"]]
        lines.append(f"\nLast updated {sgt(issue['updated_at'])}.")
        return Doc(
            source=self.name,
            doc_id=issue["key"],
            title=f"{issue['key']} {issue['summary']}",
            url=f"fixture://jira/browse/{issue['key']}",
            version=issue["version"],
            updated_at=issue["updated_at"],
            text="\n".join(lines),
            container=issue["project"],
        )

    def can_access(self, user, doc_id):
        state = load_state()
        issue = self._find(state, doc_id)
        name = user["name"]
        project = state["jira"]["projects"].get(issue["project"], {})
        if name not in project.get("browse", []):
            return False
        level = issue.get("security_level")
        return level is None or name in state["jira"]["security_levels"].get(level, [])


class SlackFixtureSource(_FixtureSource):
    name = "slack-fixture"

    def _items(self, state):
        return state["slack"]["threads"]

    def _id(self, item):
        return f"{item['channel']}:{item['ts']}"

    def _doc(self, state, thread):
        channel = state["slack"]["channels"][thread["channel"]]
        root = thread["messages"][0]["text"]
        lines = [f"#{channel['name']} thread started {sgt(thread['ts'])}"]
        lines += [f"{m['user']} ({sgt(m['ts'])}): {m['text']}" for m in thread["messages"]]
        return Doc(
            source=self.name,
            doc_id=self._id(thread),
            title=f"#{channel['name']}: {root[:60]}{'…' if len(root) > 60 else ''}",
            url=f"fixture://slack/archives/{thread['channel']}/p{thread['ts'].replace('.', '')}",
            version=thread["version"],
            updated_at=thread["updated_at"],
            text="\n".join(lines),
            container=channel["name"],
        )

    def can_access(self, user, doc_id):
        state = load_state()
        thread = self._find(state, doc_id)
        channel = state["slack"]["channels"].get(thread["channel"], {})
        return user["name"] in channel.get("members", [])

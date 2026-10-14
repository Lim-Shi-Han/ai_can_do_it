import re
from dataclasses import dataclass
from typing import Protocol

STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "what", "which", "who", "how", "why", "when",
    "did", "does", "any", "all", "from", "with", "that", "this", "there", "their", "about",
    "latest", "show", "tell", "give", "remains", "remaining", "yesterday", "today", "last",
    "week", "current", "currently", "been", "have", "has", "into", "our", "can", "you",
    "status", "done",  # a ticket field label and value, so they match unrelated tickets
}


def keywords(text, limit=6):
    seen = []
    for word in re.findall(r"[a-z0-9][a-z0-9-]+", text.lower()):
        if len(word) > 2 and word not in STOPWORDS and word not in seen:
            seen.append(word)
    return seen[:limit]


@dataclass(frozen=True)
class Candidate:
    source: str
    doc_id: str
    title: str
    container: str = ""
    version: int | str | None = None


@dataclass
class Doc:
    source: str
    doc_id: str
    title: str
    url: str
    version: int | str
    updated_at: str
    text: str
    container: str = ""


class Source(Protocol):
    name: str

    def search(self, query: str, incident_id: str | None = None, limit: int = 10) -> list[Candidate]:
        """Find candidates. Results are not filtered for the asker."""

    def can_access(self, user: dict, doc_id: str) -> bool:
        """Live check against the platform. Must not use a cache."""

    def fetch(self, doc_id: str) -> Doc:
        """Live fetch of the current version."""

    def changes_since(self, ts: str | None) -> list[Candidate]:
        """Documents created or updated after ts (ISO 8601 UTC). None means everything."""

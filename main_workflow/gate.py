from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass


@dataclass
class Decision:
    source: str
    doc_id: str
    title: str
    container: str
    allowed: bool
    reason: str
    version: int | str | None = None
    indexed_version: int | str | None = None

    def to_dict(self):
        return asdict(self)


def _decide(user, c, source):
    if source is None:
        return Decision(c.source, c.doc_id, c.title, c.container, False, "source_unavailable"), None
    try:
        allowed = source.can_access(user, c.doc_id)
        reason = "platform_allowed" if allowed else "platform_denied"
    except Exception as exc:
        allowed, reason = False, f"check_failed:{type(exc).__name__}"

    decision = Decision(c.source, c.doc_id, c.title, c.container, allowed, reason, indexed_version=c.version)
    if not allowed:
        return decision, None
    try:
        doc = source.fetch(c.doc_id)
    except Exception as exc:
        decision.allowed, decision.reason = False, f"fetch_failed:{type(exc).__name__}"
        return decision, None
    decision.version = doc.version
    if c.version is not None and str(c.version) != str(doc.version):
        decision.reason += f";refreshed:v{c.version}->v{doc.version}"
    return decision, doc


def check(user, candidates, sources, index=None):
    """Fail closed: anything that cannot be checked or fetched is denied.
    Candidates are checked in parallel, each live on its platform. Allowed documents are fetched live,
    and the index is refreshed if it held an older version."""
    unique, seen = [], set()
    for c in candidates:
        if (c.source, c.doc_id) not in seen:
            seen.add((c.source, c.doc_id))
            unique.append(c)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: _decide(user, c, sources.get(c.source)), unique))

    docs, decisions = [], []
    for decision, doc in results:
        if doc is not None:
            # SQLite connections stay on this thread, so the index is updated here, not in the workers
            if index is not None and "refreshed:" in decision.reason:
                index.upsert(doc)
            docs.append(doc)
        decisions.append(decision)
    return docs, decisions

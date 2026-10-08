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


def check(user, candidates, sources, index=None):
    """Fail closed: anything that cannot be checked or fetched is denied.
    Allowed documents are fetched live, and the index is refreshed if it held an older version."""
    docs, decisions, seen = [], [], set()
    for c in candidates:
        key = (c.source, c.doc_id)
        if key in seen:
            continue
        seen.add(key)

        source = sources.get(c.source)
        if source is None:
            decisions.append(Decision(c.source, c.doc_id, c.title, c.container, False, "source_unavailable"))
            continue
        try:
            allowed = source.can_access(user, c.doc_id)
            reason = "platform_allowed" if allowed else "platform_denied"
        except Exception as exc:
            allowed, reason = False, f"check_failed:{type(exc).__name__}"

        decision = Decision(c.source, c.doc_id, c.title, c.container, allowed, reason,
                            indexed_version=c.version)
        if allowed:
            try:
                doc = source.fetch(c.doc_id)
            except Exception as exc:
                decision.allowed, decision.reason = False, f"fetch_failed:{type(exc).__name__}"
            else:
                decision.version = doc.version
                if c.version is not None and str(c.version) != str(doc.version):
                    decision.reason += f";refreshed:v{c.version}->v{doc.version}"
                    if index is not None:
                        index.upsert(doc)
                docs.append(doc)
        decisions.append(decision)
    return docs, decisions

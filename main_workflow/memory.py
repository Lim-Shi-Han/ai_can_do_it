import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

TAG_RE = re.compile(r"\[S\d+\]")


@dataclass
class Turn:
    question: str
    answer: str
    cited: list = field(default_factory=list)   # (source, doc_id, version)
    seq: int | None = None                       # audit entry of the answer, used to redact it in the UI


class Memory:
    """Chat history for one user. Before every new question, each earlier turn is kept only if
    the user can still read every source it cited and those sources have not changed since."""

    def __init__(self, user, max_turns=6, keep_turns=50):
        self.user = user
        self.max_turns = max_turns      # turns sent to the model
        self.keep_turns = keep_turns    # turns still re-checked, because the UI still shows them
        self.turns = []
        self.incident_id = None   # from the user's own questions, so it survives dropped turns

    def add(self, question, answer, cited, incident_id=None, seq=None):
        self.incident_id = incident_id or self.incident_id
        self.turns.append(Turn(question, answer, cited, seq))
        self.turns = self.turns[-self.keep_turns:]

    def _status(self, user, sources, source_name, doc_id):
        source = sources.get(source_name)
        if source is None:
            return False, None, "source_unavailable"
        try:
            if not source.can_access(user, doc_id):
                return False, None, "access_revoked"
            return True, str(source.fetch(doc_id).version), "ok"
        except Exception as exc:
            return False, None, f"check_failed:{type(exc).__name__}"

    def revalidate(self, user, sources):
        keys = list(dict.fromkeys((s, d) for turn in self.turns for s, d, _ in turn.cited))
        live = {}
        if keys:
            with ThreadPoolExecutor(max_workers=8) as pool:
                live = dict(zip(keys, pool.map(lambda k: self._status(user, sources, *k), keys)))
        kept, dropped = [], []
        for turn in self.turns:
            problems = []
            for source_name, doc_id, version in turn.cited:
                allowed, live_version, reason = live[(source_name, doc_id)]
                if not allowed:
                    problems.append({"source": source_name, "doc_id": doc_id, "reason": reason})
                elif live_version != str(version):
                    problems.append({"source": source_name, "doc_id": doc_id,
                                     "reason": f"changed:v{version}->v{live_version}"})
            if problems:
                dropped.append({"question": turn.question, "seq": turn.seq, "problems": problems})
            else:
                kept.append(turn)
        self.turns = kept
        return dropped

    def messages(self):
        out = []
        for turn in self.turns[-self.max_turns:]:
            out.append({"role": "user", "content": turn.question})
            out.append({"role": "assistant", "content": TAG_RE.sub("", turn.answer)})
        return out

    def clear(self):
        self.turns = []
        self.incident_id = None

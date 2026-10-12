import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("AUDIT_DB") or Path(__file__).resolve().parent / "audit.db")
GENESIS = "0" * 64


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def entry_hash(prev_hash, seq, ts, user, event, data_json):
    material = "\n".join([prev_hash, str(seq), ts, user, event, data_json])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.head_path = self.path.with_suffix(".head")
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                seq INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                user TEXT NOT NULL,
                event TEXT NOT NULL,
                data TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            )"""
        )

    def append(self, user, event, data):
        data_json = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        # IMMEDIATE takes the write lock before reading the last hash, so concurrent writers queue up
        self.db.execute("BEGIN IMMEDIATE")
        try:
            last = self.db.execute("SELECT seq, hash FROM entries ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
            ts = now_utc()
            digest = entry_hash(prev, seq, ts, user, event, data_json)
            self.db.execute(
                "INSERT INTO entries (seq, ts, user, event, data, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (seq, ts, user, event, data_json, prev, digest),
            )
            # kept outside the table so that deleting the newest rows is also detectable
            self.head_path.write_text(f"{seq} {digest}\n", encoding="utf-8")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return seq

    def recent(self, limit=20, events=None):
        sql = "SELECT seq, ts, user, event, data FROM entries"
        args = []
        if events:
            sql += f" WHERE event IN ({','.join('?' * len(events))})"
            args += list(events)
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        return [
            {"seq": seq, "ts": ts, "user": user, "event": event, "data": json.loads(data)}
            for seq, ts, user, event, data in self.db.execute(sql, args)
        ]

    def verify(self):
        problems = []
        prev, expected_seq = GENESIS, 1
        rows = self.db.execute(
            "SELECT seq, ts, user, event, data, prev_hash, hash FROM entries ORDER BY seq"
        ).fetchall()
        for seq, ts, user, event, data, prev_hash, digest in rows:
            if seq != expected_seq:
                problems.append((expected_seq, f"entries {expected_seq}..{seq - 1} missing"))
            if prev_hash != prev:
                problems.append((seq, "prev_hash does not match previous entry"))
            if entry_hash(prev_hash, seq, ts, user, event, data) != digest:
                problems.append((seq, "content changed after it was written"))
            prev, expected_seq = digest, seq + 1

        if self.head_path.exists():
            head_seq, head_hash = self.head_path.read_text(encoding="utf-8").split()
            last_seq = rows[-1][0] if rows else 0
            if int(head_seq) != last_seq or (rows and rows[-1][6] != head_hash):
                problems.append((int(head_seq), f"log ends at {last_seq}, head file says {head_seq}"))
        elif rows:
            problems.append((0, "head file missing"))
        return len(rows), problems

    def query(self, user=None, since=None, event=None, source=None, container=None, doc_id=None):
        sql = "SELECT seq, ts, user, event, data FROM entries WHERE 1=1"
        args = []
        if user:
            sql += " AND user = ?"
            args.append(user)
        if since:
            sql += " AND ts >= ?"
            args.append(since)
        if event:
            sql += " AND event = ?"
            args.append(event)
        out = []
        for seq, ts, who, ev, data_json in self.db.execute(sql + " ORDER BY seq", args):
            data = json.loads(data_json)
            decisions = data.get("decisions", [])
            if source or container or doc_id:
                decisions = [
                    d for d in decisions
                    if (not source or d["source"] == source)
                    and (not container or d.get("container") == container)
                    and (not doc_id or d["doc_id"] == doc_id)
                ]
                if not decisions:
                    continue
            out.append({"seq": seq, "ts": ts, "user": who, "event": ev, "data": data, "matched": decisions})
        return out

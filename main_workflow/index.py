import sqlite3
from pathlib import Path

from .audit import now_utc
from .sources.base import Candidate, keywords

DEFAULT_DB = Path(__file__).resolve().parent / "index.db"


class Index:
    """Search index for candidate selection only. Text here never reaches the model;
    the gate re-checks access and re-fetches every document live."""

    def __init__(self, path=DEFAULT_DB):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                source TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                title TEXT NOT NULL,
                container TEXT NOT NULL,
                version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                PRIMARY KEY (source, doc_id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(source UNINDEXED, doc_id UNINDEXED, title, body, tokenize='porter unicode61');
            CREATE TABLE IF NOT EXISTS sync_state (
                source TEXT PRIMARY KEY,
                cursor TEXT NOT NULL,
                last_run TEXT NOT NULL,
                last_changes INTEGER NOT NULL
            );
            """
        )

    def upsert(self, doc):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc.source, doc.doc_id, doc.title, doc.container, str(doc.version), doc.updated_at, now_utc()),
            )
            self.db.execute("DELETE FROM docs_fts WHERE source = ? AND doc_id = ?", (doc.source, doc.doc_id))
            self.db.execute("INSERT INTO docs_fts VALUES (?, ?, ?, ?)", (doc.source, doc.doc_id, doc.title, doc.text))

    def remove(self, source, doc_id):
        with self.db:
            self.db.execute("DELETE FROM docs WHERE source = ? AND doc_id = ?", (source, doc_id))
            self.db.execute("DELETE FROM docs_fts WHERE source = ? AND doc_id = ?", (source, doc_id))

    def doc_ids(self, source):
        return {r[0] for r in self.db.execute("SELECT doc_id FROM docs WHERE source = ?", (source,))}

    def version(self, source, doc_id):
        row = self.db.execute("SELECT version FROM docs WHERE source = ? AND doc_id = ?", (source, doc_id)).fetchone()
        return row[0] if row else None

    def search(self, query, incident_id=None, source=None, limit=10):
        terms = keywords(query)
        if incident_id:
            terms.insert(0, incident_id)
        if not terms:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        sql = """
            SELECT d.source, d.doc_id, d.title, d.container, d.version
            FROM docs_fts f JOIN docs d ON d.source = f.source AND d.doc_id = f.doc_id
            WHERE docs_fts MATCH ?"""
        args = [match]
        if source:
            sql += " AND d.source = ?"
            args.append(source)
        sql += " ORDER BY bm25(docs_fts, 0, 0, 5.0, 1.0) LIMIT ?"
        args.append(limit)
        return [Candidate(*row) for row in self.db.execute(sql, args)]

    def all_docs(self):
        return [
            Candidate(*row)
            for row in self.db.execute("SELECT source, doc_id, title, container, version FROM docs ORDER BY source, title")
        ]

    def has_source(self, source):
        return self.db.execute("SELECT 1 FROM sync_state WHERE source = ?", (source,)).fetchone() is not None

    def cursor(self, source):
        row = self.db.execute("SELECT cursor FROM sync_state WHERE source = ?", (source,)).fetchone()
        return row[0] if row else None

    def mark_synced(self, source, cursor, changes):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sync_state VALUES (?, ?, ?, ?)", (source, cursor, now_utc(), changes)
            )

    def status(self):
        counts = dict(self.db.execute("SELECT source, COUNT(*) FROM docs GROUP BY source"))
        return [
            {"source": s, "docs": counts.get(s, 0), "cursor": c, "last_run": r, "last_changes": n}
            for s, c, r, n in self.db.execute("SELECT * FROM sync_state ORDER BY source")
        ]

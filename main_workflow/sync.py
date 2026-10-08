import argparse
import sys
import time
from datetime import datetime, timedelta

from .audit import AuditLog, now_utc
from .index import Index
from .sources import load_sources

OVERLAP = timedelta(minutes=2)


def sync_source(index, source, full=False):
    started = now_utc()
    cursor = None if full or not index.has_source(source.name) else index.cursor(source.name)
    if cursor:
        cursor = (datetime.fromisoformat(cursor.replace("Z", "+00:00")) - OVERLAP).isoformat().replace("+00:00", "Z")

    changes = source.changes_since(cursor)
    updated, removed = [], []
    for c in changes:
        if not full and c.version is not None and index.version(source.name, c.doc_id) == str(c.version):
            continue
        try:
            doc = source.fetch(c.doc_id)
        except RuntimeError:
            index.remove(source.name, c.doc_id)
            removed.append(c.doc_id)
            continue
        index.upsert(doc)
        updated.append({"doc_id": doc.doc_id, "title": doc.title, "version": doc.version, "updated_at": doc.updated_at})

    if full:
        seen = {c.doc_id for c in changes}
        for doc_id in index.doc_ids(source.name) - seen:
            index.remove(source.name, doc_id)
            removed.append(doc_id)

    index.mark_synced(source.name, started, len(updated) + len(removed))
    return updated, removed


def run_once(index, sources, audit, full=False):
    for source in sources.values():
        try:
            updated, removed = sync_source(index, source, full)
        except Exception as exc:
            print(f"{now_utc()} {source.name}: sync failed: {exc}", file=sys.stderr)
            continue
        if updated or removed:
            audit.append("system", "sync", {"source": source.name, "updated": updated, "removed": removed, "full": full})
        detail = ", ".join(f"{u['doc_id']} v{u['version']}" for u in updated)
        print(f"{now_utc()} {source.name}: {len(updated)} updated, {len(removed)} removed" + (f" ({detail})" if detail else ""))


def main():
    parser = argparse.ArgumentParser(prog="main_workflow.sync")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--full", action="store_true", help="re-fetch everything and drop deleted documents")
    parser.add_argument("--interval", type=int, default=60, help="seconds between polls")
    args = parser.parse_args()

    index = Index()
    if args.command == "status":
        for row in index.status():
            print(f"{row['source']:<11} {row['docs']:>4} docs  last run {row['last_run']}  "
                  f"cursor {row['cursor']}  last changes {row['last_changes']}")
        return

    sources, audit = load_sources(), AuditLog()
    run_once(index, sources, audit, full=args.full)
    while not args.once:
        time.sleep(args.interval)
        run_once(index, sources, audit)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

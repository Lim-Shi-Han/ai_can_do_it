import sys

from .base import Candidate, Doc, Source


def _confluence():
    from .confluence import ConfluenceSource
    return ConfluenceSource()


def _gdrive():
    from .gdrive import GDriveSource
    return GDriveSource()


FACTORIES = [_confluence, _gdrive]


def load_sources():
    sources = {}
    for factory in FACTORIES:
        try:
            source = factory()
        except ValueError as exc:
            print(f"Skipping {factory.__name__.lstrip('_')}: {exc}", file=sys.stderr)
            continue
        sources[source.name] = source
    if not sources:
        raise RuntimeError("No sources are configured")
    return sources


__all__ = ["Candidate", "Doc", "Source", "load_sources"]

import os
import sys

from .base import Candidate, Doc, Source


def _confluence():
    from .confluence import ConfluenceSource
    return ConfluenceSource()


def _gdrive():
    from .gdrive import GDriveSource
    return GDriveSource()


def _jira():
    from .jira import JiraSource
    return JiraSource()


def _slack():
    try:
        from .slack import SlackSource
        return SlackSource()
    except (ImportError, ValueError) as exc:
        # rehearse on the stand-in until Slack is configured
        print(f"Using the Slack stand-in: {exc}", file=sys.stderr)
        from stand_in_jira_slack.sources import SlackFixtureSource
        return SlackFixtureSource()


FACTORIES = [_confluence, _gdrive, _jira, _slack]


def load_sources():
    # ONLY_SOURCES=slack (comma-separated) rehearses with some platforms before the others are ready
    only = {name for name in os.environ.get("ONLY_SOURCES", "").split(",") if name}
    sources = {}
    for factory in FACTORIES:
        if only and factory.__name__.lstrip("_") not in only:
            continue
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

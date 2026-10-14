"""Put every configured platform back to the demo's base state, before the story starts.

Used by the console's Reset rehearsal and by `python -m main_workflow.cli reset`.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE_CLI = REPO / "stand_in_jira_slack" / "fixture_cli.py"
JIRA_CLI = REPO / "jira" / "jira_cli.py"
GDRIVE_CLI = REPO / "gdrive" / "gdrive_cli.py"
DEMO_DRIVE = REPO / "gdrive" / "demo_drive.py"
CONFLUENCE_CLI = REPO / "confluence" / "confluence_cli.py"
DEMO_SPACES = REPO / "confluence" / "demo_spaces.py"
SLACK_CLI = REPO / "slack_demo" / "slack_cli.py"
REBUILD_TIMEOUT = 1800   # recreating a Jira project and reserving its keys takes minutes


def run_cli(args, timeout=120):
    done = subprocess.run([sys.executable, *map(str, args)], cwd=REPO, capture_output=True, text=True, timeout=timeout)
    if done.returncode == 0:
        return True, (done.stdout.strip() or "done").splitlines()[0]
    return False, (done.stderr.strip() or done.stdout.strip() or "failed").splitlines()[-1]


def jira_projects_with_demo_tickets():
    """Projects holding tickets beyond the seed. Jira never reuses a key, so only a rebuild gives them back."""
    from jira.jira_cli import Jira, load_local_env, load_seed, until_permitted
    load_local_env()
    seed = load_seed()
    projects = [p["key"] for p in seed["projects"]]
    seeded = {issue["key"] for issue in seed["issues"]}
    api = Jira()
    found = {issue["key"] for issue in until_permitted(api, projects, lambda: api.search(f"project in ({', '.join(projects)})"))}
    return sorted({key.rsplit("-", 1)[0] for key in found - seeded})


def reset_platforms(sources):
    """Reset each configured platform (sources: their names). Returns (ok, summary)."""
    steps = [([FIXTURE_CLI, "reset"], 120)]
    if "jira" in sources:
        demo_projects = jira_projects_with_demo_tickets()
        if demo_projects:
            steps.append(([JIRA_CLI, "rebuild", "--yes", "--only", ",".join(demo_projects)], REBUILD_TIMEOUT))
        steps.append(([JIRA_CLI, "reset"], 300))
    if "confluence" in sources:
        steps.append(([CONFLUENCE_CLI, "restore-runbook"], 120))
        steps.append(([DEMO_SPACES, "incident-report", "--remove"], 120))   # step 6's report, gone for good
    if "slack" in sources:
        steps.append(([SLACK_CLI, "reset"], 300))
    if "gdrive" in sources:
        # Terrance off the processor folder, and the demo's uploads trashed by their owners
        steps.append(([DEMO_DRIVE, "reset", "--yes"], 300))

    ok, summary = True, []
    for args, timeout in steps:
        step_ok, text = run_cli(args, timeout)
        ok = ok and step_ok
        summary.append(text)
    return ok, "; ".join(summary)

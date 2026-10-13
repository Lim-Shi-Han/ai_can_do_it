# Stand-in Jira and Slack

Temporary sources so the full four-platform demo can be rehearsed before the real Jira and Slack sources are ready. They implement the same `Source` interface as `main_workflow/sources/`, but read `state.json` instead of calling an API.

They are registered as `jira-fixture` and `slack-fixture`, so every citation and audit entry shows they are stand-ins. Citation links use `fixture://`.

## Files

| File | Purpose |
|---|---|
| `seed.json` | The story data: Jira project `PAY` with PAY-101 to PAY-104, Slack channels `#payment-incident-001` (private) and `#payments` (public). Never changed by the scripts. |
| `state.json` | Working copy created from the seed on first use. Demo commands change this file. Ignored by Git. |
| `sources.py` | `JiraFixtureSource` and `SlackFixtureSource`. |
| `fixture_cli.py` | Shows who can see what, and changes access, ticket status, and messages during a demo. |

## Permissions in the seed

| | ShiHan | Zhao | Ivan | Elson | Sheldon | Terrance |
|---|---|---|---|---|---|---|
| PAY-101, PAY-102, PAY-103 | ✓ | ✓ | ✓ | | | |
| PAY-104 (security level) | | ✓ | ✓ | | | |
| `#payment-incident-001` threads | ✓ | ✓ | ✓ | | | |
| `#payments` thread | ✓ | ✓ | ✓ | | ✓ | ✓ |

Jira access needs browse permission on the project and, for PAY-104, membership of the `Security` level. Slack access is channel membership.

`#payment-incident-001` contains an unverified "can we just fail over now?" message, to test that Slack is never treated as an approved runbook step.

## Commands

Run from the repository root.

```bash
python3 stand_in_jira_slack/fixture_cli.py status                                   # access grid
python3 stand_in_jira_slack/fixture_cli.py revoke ShiHan slack payment-incident-001  # revocation demo
python3 stand_in_jira_slack/fixture_cli.py grant ShiHan slack payment-incident-001
python3 stand_in_jira_slack/fixture_cli.py revoke ShiHan jira PAY                     # project or security level
python3 stand_in_jira_slack/fixture_cli.py set-status PAY-101 Done --comment "DBA approved, merged"
python3 stand_in_jira_slack/fixture_cli.py post payment-incident-001 ShiHan "PAY-101 unblocked" --thread 1790733900.000000
python3 stand_in_jira_slack/fixture_cli.py reset                                    # back to the seed
```

Status changes and posts bump the item's version and update time, so the sync worker and the gate treat them like real edits.

`python3 -m main_workflow.web` resets `state.json` to the seed on every start (skip with `--keep-state`). The console's **Reset rehearsal** does the same while the server is running. Set `STAND_IN_STATE` to use a different state file.

## Replacing with the real sources

When `main_workflow/sources/jira.py` or `slack.py` is ready, change `_jira()` or `_slack()` in `main_workflow/sources/__init__.py` to return it. Nothing else changes. Then delete this folder and run `python3 -m main_workflow.sync --full` to drop the stand-in documents from the index.

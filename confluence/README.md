# Confluence demo spaces

Site: `https://hackathontencent.atlassian.net/wiki`. Four spaces hold the fictional Company A content. Only standing documents exist before the demo; Ivan's incident report (step 6) and runbook v2 (step 11) are created live.

| Space | Purpose | ShiHan | Zhao | Ivan | Elson | Sheldon | Terrance |
|---|---|---|---|---|---|---|---|
| `HANDBOOK` Company Handbook | Policies for every employee | Viewer | Admin | Collaborator | Viewer | Viewer | · |
| `PAYOPS` Payment Operations | Payments engineering | Collaborator | Admin | Collaborator | Viewer | · | · |
| `FINOPS` Finance Operations | Reconciliation, month-end, FX | · | Admin | · | · | Collaborator | · |
| `SECOPS` Security | Security team only | · | Admin | Collaborator | · | · | · |

Viewer can read and comment; Collaborator can also add, edit, and restrict pages. Terrance, the external contractor, has no Confluence access.

## Files

| File | Purpose |
|---|---|
| `demo_spaces.json` | Spaces, who gets which role, the pages (with author and comments), and the old pages moved to the trash |
| `demo_spaces.py` | Creates the spaces, sets the roles, and writes each page **as its author** using their own token |
| `seed_pages.json` | Runbook v1 and v2 only, used by the console's runbook buttons |
| `confluence_cli.py` | Runbook commands (`update-runbook`, `restore-runbook`), `read`, `list`, `check` |
| `page_manifest.json` | Snapshot of the runbook's ID, URL, and version, written by `confluence_cli.py list` |

## Credentials

Confluence is on the same Atlassian site as Jira, so both tools fall back to `JIRA_EMAIL` and `JIRA_API_TOKEN` when `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` are not set. Per-person tokens (`JIRA_TOKEN_SHIHAN`, `JIRA_TOKEN_IVAN`, `JIRA_TOKEN_SHELDON`) let pages, comments, and runbook versions show their real authors; without them, the API account (Zhao) writes and the author's name goes into the text. The app reads the spaces in `CONFLUENCE_SPACE_KEYS`.

## Set up and seed

```bash
python3 confluence/demo_spaces.py setup    # create missing spaces, set each person's role, remove "all licensed users"
python3 confluence/demo_spaces.py seed     # move old pages to the trash, write pages and comments as their authors
python3 confluence/demo_spaces.py check    # roles per space
python3 confluence/demo_spaces.py access   # who can read each page, according to Confluence
```

## Step 6: the incident report

```bash
python3 confluence/demo_spaces.py incident-report            # Ivan publishes it in PAYOPS and restricts it to ShiHan, Zhao, and Ivan
python3 confluence/demo_spaces.py incident-report --remove   # rehearsal reset: deletes it for good
```

Ivan writes and restricts the page with his own token (`JIRA_TOKEN_IVAN`); the command then asks Confluence who can open it and fails unless it is exactly the readers. The text is `incident_report` in `demo_spaces.json`. It must never name PAY-102 or its title: an answer that repeats a ticket the asker cannot see is blocked. `--remove` purges the page rather than trashing it, because Confluence keeps a trashed page's title taken. The console's **Step 6** button and **Reset rehearsal** run these commands.

Both commands are safe to rerun: unchanged pages and comment threads are left alone.

This site uses **space roles** (`/wiki/api/v2/space-role-mode` returns `ROLES`), so the older per-permission API is refused; `demo_spaces.py` assigns roles through `/wiki/api/v2/spaces/{id}/role-assignments` instead.

Page text avoids the demo questions' words unless the page is meant to answer them (the runbook, the incident response policy, the access request guide, the reconciliation guide). Security pages live in `SECOPS`, so security questions from people outside the security team are refused at space level.

## Runbook and freshness demo

```bash
python3 confluence/confluence_cli.py update-runbook    # v2: adds the approved standby-region failover step (step 11)
python3 confluence/confluence_cli.py restore-runbook   # back to the v1 text, as a new version
python3 confluence/confluence_cli.py list              # refresh page_manifest.json
```

Both are published as the runbook's owner (ShiHan) when `JIRA_TOKEN_SHIHAN` is set, and do nothing when the page already shows the target text. Confluence cannot delete the current version, so restoring creates a new version with the original text.

## Old pages

The eight pages of the earlier story (INC-PAY-001 described as a past incident, with the old ticket numbers) were moved to the trash on 2026-10-14 and can be restored from the space trash for 30 days. The incident response policy and the reconciliation guide were rewritten in `HANDBOOK` and `FINOPS`.

## Dummy Confluence → Qwen workflow

`dummy_workflow.py` resolves the runbook's page ID from `page_manifest.json`, fetches the **current** page text, and sends it with a question to the local vLLM endpoint (`VLLM_BASE_URL`, `VLLM_MODEL`). It is a single-page check with no permission gate; the main workflow in `main_workflow/` is the real pipeline.

```bash
python3 confluence/dummy_workflow.py --question 'What is the current payment-service recovery procedure?'
```

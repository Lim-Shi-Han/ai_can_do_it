# Development plan

| Phase | Work | Status |
|---|---|---|
| A | `sources/base.py`, `audit.py`, `gate.py`, `pipeline.py`, plus the Confluence source: the full loop working on Confluence only | ✅ Done |
| B | Jira, Slack, and Drive sources against the interface | 🟡 In progress: Drive done; Jira and Slack to do |
| C | `index.py`, `sync.py`, `memory.py`: scenarios 2 and 4 | ✅ Done (live freshness rehearsal still to run) |
| D | Run the demo script end to end, then the architecture and trust-boundary diagrams | ⬜ To do |
| E (optional) | A small web UI with a user switcher, replacing the command-line chat | ⬜ To do |

# To-do list

**Sources (Phase B)**
- [ ] Jira source `sources/jira.py`: project `PAY`, issues PAY-101 to PAY-104 labelled `INC-PAY-001`, PAY-104 at the Security issue-security level
- [ ] Slack source `sources/slack.py`: private `#payment-incident-001` (alice and sam, not bob) and public `#payments`, including one unverified "just fail over now?" message
- [ ] Register both in `sources/__init__.py`
- [ ] Confirm the Jira keys, Slack channel, and Drive file title used in `confluence/seed_pages.json` with the source owners

**Accounts and permissions**
- [ ] Upgrade Confluence and Jira to Standard (trial), so pages and issues can be restricted
- [ ] Restrict the Confluence security appendix (page 393217) to sam
- [ ] Create demo accounts and fill in `identities.json`: Atlassian account IDs for bob, sam, and carol; Slack user IDs for everyone; a Google account for alice
- [ ] `python3 gdrive/gdrive_cli.py share alice` once alice has a Google account; keep bob unshared
- [ ] Re-map alice from the seeding account to her own Atlassian account

**Demo (Phase D)**
- [ ] Rehearse the freshness demo: `confluence_cli.py update-runbook`, then ask again in the same chat and check that v2 and the new failover step are cited
- [ ] Rehearse revocation: remove alice from `#payment-incident-001` or `gdrive_cli.py unshare alice`, then ask a follow-up in the same chat
- [ ] Rehearse the contractor case as bob and compare with sam
- [ ] Rehearse the audit inquiry as carol, then edit a row and run `audit verify`
- [ ] Change "yesterday's outage" in the demo question to "INC-PAY-001", or re-date the seed data to the day before the demo
- [ ] Architecture diagram and trust-boundary diagram, with key design trade-offs
- [ ] Worked example (setup, action, actual result) for each of the five scenarios
- [ ] Open the presentation by naming FinTech / Aspire: The Internal Brain as the chosen case
- [ ] Ask the organisers whether the FinTech track has its own "The Solution Should Be" criteria (page 20 of the brief shows healthcare criteria)

**Optional**
- [ ] `check_source.py`: prints a user × document allow/deny grid for any source
- [ ] Web UI with a user switcher (Phase E)

# main_workflow

Permission-aware question answering over Confluence, Jira, Slack, and Google Drive, with a hash-chained audit trail.

Run everything from the repository root. Needs the same `.env` as `confluence/` and the local vLLM server.

```bash
python3 -m main_workflow.sync                         # keep running in another terminal; polls every 60s
python3 -m main_workflow.sync status

python3 -m main_workflow.cli ask --as alice "What caused the INC-PAY-001 outage, what is the latest recovery procedure, and what work remains?"
python3 -m main_workflow.cli chat --as alice          # /as bob switches user, /reset clears, /quit leaves

python3 -m main_workflow.cli audit query --as carol --user alice --container PAYOPS --since 30d
python3 -m main_workflow.cli audit query --as carol --doc 393217    # who retrieved this page
python3 -m main_workflow.cli audit verify
```

## Files

| File | Purpose |
|---|---|
| `sources/base.py` | The interface every platform implements: `search`, `can_access`, `fetch`, `changes_since`. |
| `sources/confluence.py` | Confluence source. Reuses the client in `confluence/confluence_cli.py` and adds search and a live per-user permission check. |
| `sources/gdrive.py` | Google Drive source. Reuses the client in `gdrive/gdrive_cli.py` with the read-only scope. Skipped with a warning until Drive is configured in `.env`. |
| `gate.py` | Checks each candidate live. A failed check or fetch counts as a denial. Only allowed documents are fetched, and the index is refreshed when it held an older version. |
| `index.py` | SQLite FTS5 index (Porter stemming) used only to pick candidates. Its text never reaches the model. |
| `sync.py` | Polls each source's `changes_since` every 60 s and updates the index. Each sync with changes is logged as a `system` audit entry. |
| `memory.py` | Chat history for one user. Before each question, earlier turns are dropped if any source they cited is revoked or has changed. |
| `pipeline.py` | Question → candidates → permission check → numbered sources → model → output check → audit entry. |
| `audit.py` | Hash-chained SQLite log with `verify` and `query`. A separate head file catches deletion of the newest entries. |
| `cli.py` | `ask`, `chat` (`/as <user>` switches user), `audit query`, `audit verify`. |
| `identities.json` | The four demo users and their accounts on each platform. |

## Flow

1. Look up the asker in `identities.json`.
2. Candidates come from the index for every source that has been synced, and from the source's live search otherwise. Either way, search runs as the service account and its results never reach the model directly.
3. `gate.check` asks each platform, live, whether the asker can read each candidate. Errors count as denials. Only allowed documents are fetched.
4. Allowed documents become numbered sources `[S1]…` for the model.
5. `check_answer` removes citation tags that point nowhere, and replaces the answer if it names a denied document.
6. The question, every allow/deny decision, the cited versions, and the answer are written to `audit.db`.

When nothing is allowed, the reply is the same fixed sentence as when nothing matched, so a denial does not reveal that a document exists.

## Freshness and revocation

- New documents become searchable within one sync interval (60 s by default). Each poll re-reads the last 2 minutes so edits near a poll boundary are not missed.
- Documents already in the index are always answered at their live version: the gate fetches every allowed document, and if the index was behind, it is updated during that question and the decision is marked `refreshed:vN->vM`.
- Permissions are never cached. In chat, every earlier turn is re-checked before the next question. A turn whose sources were revoked or changed is removed from the model's context and logged as `context_dropped`. The user sees only that earlier answers were removed, not which document caused it.
- Switching user with `/as` starts an empty history.

## Adding a source

Implement the `Source` protocol in `sources/base.py` (`search`, `can_access`, `fetch`, `changes_since`) and register it in `sources/__init__.py`. Set `container` to the project, channel, or folder so audit queries can filter on it.

## Audit trail

Each entry stores `sha256(prev_hash, seq, ts, user, event, data)`. `audit.head` holds the latest seq and hash, so deleting the newest rows is detected as well as editing or removing rows in the middle. To show tampering in the demo:

```bash
sqlite3 main_workflow/audit.db "update entries set data = replace(data, 'platform_denied', 'platform_allowed') where seq = 2"
python3 -m main_workflow.cli audit verify
```

Only users with `can_audit` can query the trail, and their queries are logged too.

## Identities

`alice` is mapped to the account that seeded PAYOPS. The other users have no account IDs yet, so every check denies them. Fill in the Atlassian account IDs, Slack user IDs, and Google emails once the demo accounts exist.

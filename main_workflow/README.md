# Development plan

| Phase | Work | Status |
|---|---|---|
| A | `sources/base.py`, `audit.py`, `gate.py`, `pipeline.py`, plus the Confluence source: the full loop working on Confluence only | ✅ Done |
| B | Jira, Slack, and Drive sources against the interface | 🟡 In progress: Drive done; Jira and Slack running on stand-ins (`stand_in_jira_slack/`) |
| C | `index.py`, `sync.py`, `memory.py`: scenarios 2 and 4 | ✅ Done (live freshness rehearsal still to run) |
| D | Run the demo script end to end, then the architecture and trust-boundary diagrams | 🟡 In progress: demo flow runs in the web UI; rehearsal, diagrams, and worked examples to do |
| E (optional) | A small web UI with a user switcher, replacing the command-line chat | ✅ Done (`python3 -m main_workflow.web`) |

# To-do list

**Sources (Phase B)**
- [ ] Jira source `sources/jira.py`: project `PAY`, issues PAY-101 to PAY-104 labelled `INC-PAY-001`, PAY-104 at the Security issue-security level
- [ ] Slack source `sources/slack.py`: private `#payment-incident-001` (ShiHan, Ivan, and Zhao; not Sheldon or Terrance) and public `#payments`, including one unverified "just fail over now?" message
- [x] Stand-in Jira and Slack sources in `stand_in_jira_slack/` for rehearsals
- [ ] Swap the stand-ins for the real sources in `sources/__init__.py`
- [ ] Confirm the Jira keys, Slack channel, and Drive file title used in `confluence/seed_pages.json` with the source owners

**Accounts and permissions**
- [ ] Upgrade Confluence and Jira to Standard (trial), so pages and issues can be restricted
- [ ] Restrict Jira and Confluence to match the Identities table below: all six accounts can currently open everything in Jira `PAY` and Confluence `PAYOPS` (checked 2026-10-13)
- [ ] Restrict the Confluence security appendix (page 393217) to Ivan and Zhao (Zhao's account is also the system's API account, which must keep read access)
- [x] Create demo accounts and fill in `identities.json`: Atlassian account IDs and Google emails for all six users
- [ ] Slack user IDs in `identities.json` once real Slack exists
- [ ] `python3 gdrive/gdrive_cli.py share ShiHan Ivan Sheldon`; keep Terrance unshared (Zhao's Google account owns the folder)
- [x] Re-map ShiHan from the seeding account to a separate Atlassian account

**Demo (Phase D)**
- [ ] Rehearse the freshness demo: console **Publish runbook update**, then ask again in the same chat and check that the new version and failover step are cited; **Restore original runbook** afterwards
- [ ] Rehearse revocation: console **Remove** ShiHan from `#payment-incident-001` (or from Jira project `PAY`), then ask a follow-up in the same chat
- [ ] Rehearse the contractor case as Terrance and compare with Ivan
- [ ] Rehearse the audit inquiry as Elson, then edit a row and verify; also revoke Elson's auditor role from the console
- [ ] Change "yesterday's outage" in the demo question to "INC-PAY-001", or re-date the seed data to the day before the demo
- [ ] Architecture diagram and trust-boundary diagram, with key design trade-offs
- [ ] Worked example (setup, action, actual result) for each of the five scenarios
- [ ] Open the presentation by naming FinTech / Aspire: The Internal Brain as the chosen case
- [ ] Ask the organisers whether the FinTech track has its own "The Solution Should Be" criteria (page 20 of the brief shows healthcare criteria)

**Optional**
- [x] User × document allow/deny grid (the console's access grid, checked live)
- [x] Web UI with a user switcher and a platform console (Phase E)

# main_workflow

**Corporate Chat with Dynamic Access**: permission-aware question answering over Confluence, Jira, Slack, and Google Drive, with a hash-chained audit trail.

Run everything from the repository root. Needs the same `.env` as `confluence/`, the local vLLM server, and `main_workflow/identities.json`. That file is not in Git: get it from a teammate, or start from the placeholder copy:

```bash
cp main_workflow/identities.example.json main_workflow/identities.json   # then fill in real Google emails
```

## Web UI

```bash
python3 -m main_workflow.web                # http://127.0.0.1:8090, syncs every 60 s in the background
python3 -m main_workflow.web --keep-state   # same, but keep the current stand-in Jira/Slack data
ssh -L 8090:localhost:8090 <dgx-host>       # from your laptop, then open http://localhost:8090
```

Every server start resets the stand-in Jira and Slack data to `stand_in_jira_slack/seed.json` (unless `--keep-state`), so leftovers from tests or earlier rehearsals do not carry over. The reset shows in the console's activity feed. Use `--port` if 8090 is taken.

| Page | Purpose |
|---|---|
| `/` | The chat. Demo sign-in dropdown (stands in for SSO), answers split into Confirmed / Unconfirmed / Missing, citation cards, sync status, and a link to the console. The Audit tab appears only for users with `can_audit` (Elson); the server re-checks the role on every audit request. |
| `/console` | Source platform console. Simulates an admin changing access or content in Slack, Jira, Drive, and Confluence, plus the chat's own auditor role. Shows a live access grid, current channel and project members, the gate's latest allow/deny decisions, and an activity feed. The chat itself never changes permissions. |

Open the two pages side by side for the demo. The server binds to `127.0.0.1` only; the console has no login, so do not expose it.

### Chat behaviour worth knowing

- A page reload or the Back button keeps the same chat (per browser tab). A new chat starts only when you switch user, click **Reset**, restart the server, or click **Reset rehearsal** in the console.
- When a chat is cleared from outside (Reset rehearsal or a server restart), the page says why and puts your question back in the input box.
- When access is revoked, earlier answers that used the revoked sources are removed from the model's context and blanked on screen ("This answer was removed…"). The user is never told which document or platform caused it.
- When nothing the user can see is relevant, the reply is a fixed sentence, the same as when nothing exists, so a denial does not reveal that a document exists.

### Demo flow

Before each run:

1. Stop the server, clear the audit trail, and start it again (this also resets the stand-in data):

   ```bash
   rm -f main_workflow/audit.db main_workflow/audit.head
   python3 -m main_workflow.web
   ```

2. Console: **Reset rehearsal**, then **Refresh** the access grid. ShiHan should have ✓ on both Slack channels and PAY-101 to PAY-103.

Then:

1. **Unified query.** Chat as ShiHan: ask the main INC-PAY-001 question. Citations come from Confluence, Jira, and Slack (Drive too, once the folder is shared with ShiHan).
2. **Freshness.** Console: **Publish runbook update**, then **Sync now**. Ask again in the same chat: the answer cites the new runbook version and the failover step, and the earlier answer is removed because its runbook version is out of date.
3. **Revocation.** Console: check the Slack card shows ShiHan as a member of `#payment-incident-001`, then click **Remove**. Ask a follow-up in the same chat: the "earlier answers were removed" banner appears, the earlier Slack answer is blanked, and no Slack citations appear. The console shows the DENY decisions. To give access back mid-demo, use **Add**, not Reset rehearsal (which clears every chat).
4. **Restricted user.** Chat as Terrance, then as Ivan, with the same security question. Terrance gets nothing restricted and no hint that anything was hidden; Ivan sees PAY-104.
5. **Audit inquiry.** Chat as Elson: Audit tab, filter on ShiHan, **Verify chain**. Edit a row with `sqlite3` in a terminal (see Audit trail below), then verify again: it turns red. Optionally, console: **Revoke auditor role** for Elson; the next audit search is refused and the Audit tab disappears.
6. Console: **Reset rehearsal** (or **Restore original runbook**) at the end. Confluence cannot delete the current version, so the original text comes back as a new version.

## Command line

`AUDIT_DB`, `STAND_IN_STATE`, and `IDENTITIES_FILE` override the default locations of the audit database, the stand-in Jira/Slack state, and the users file, for example to run a second copy of the server without touching the demo data.

```bash
python3 -m main_workflow.sync                         # keep running in another terminal; polls every 60s
python3 -m main_workflow.sync status

python3 -m main_workflow.cli ask --as ShiHan "What caused the INC-PAY-001 outage, what is the latest recovery procedure, and what work remains?"
python3 -m main_workflow.cli chat --as ShiHan          # /as Terrance switches user, /reset clears, /quit leaves

python3 -m main_workflow.cli audit query --as Elson --user ShiHan --container PAYOPS --since 30d
python3 -m main_workflow.cli audit query --as Elson --doc 393217    # who retrieved this page
python3 -m main_workflow.cli audit verify
```

## Files

| File | Purpose |
|---|---|
| `sources/base.py` | The interface every platform implements: `search`, `can_access`, `fetch`, `changes_since`. |
| `sources/confluence.py` | Confluence source. Reuses the client in `confluence/confluence_cli.py` and adds search and a live per-user permission check. |
| `../stand_in_jira_slack/` | Stand-in Jira and Slack sources (`jira-fixture`, `slack-fixture`) until the real ones are ready. See its README. |
| `sources/gdrive.py` | Google Drive source. Reuses the client in `gdrive/gdrive_cli.py` with the read-only scope. Skipped with a warning until Drive is configured in `.env`. |
| `gate.py` | Checks each candidate live. A failed check or fetch counts as a denial. Only allowed documents are fetched, and the index is refreshed when it held an older version. |
| `index.py` | SQLite FTS5 index (Porter stemming) used only to pick candidates. Its text never reaches the model. |
| `sync.py` | Polls each source's `changes_since` every 60 s and updates the index. Each sync with changes is logged as a `system` audit entry. |
| `memory.py` | Chat history for one user. Before each question, earlier turns are dropped if any source they cited is revoked or has changed. |
| `pipeline.py` | Question → candidates → permission check → numbered sources → model → output check → audit entry. |
| `audit.py` | Hash-chained SQLite log with `verify` and `query`. A separate head file catches deletion of the newest entries. |
| `web.py`, `static/` | Web UI: JSON API over the same pipeline, background sync thread, per-tab chat sessions, and the console actions (which call the existing `fixture_cli.py`, `gdrive_cli.py`, and `confluence_cli.py`, or change the auditor role in `identities.json`). |
| `cli.py` | `ask`, `chat` (`/as <user>` switches user), `audit query`, `audit verify`. |
| `identities.json` | The six demo users and their accounts on each platform. Ignored by Git because it holds real email addresses and the console rewrites it; copy `identities.example.json` (placeholder emails) or get the real file from a teammate. |

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
- Permissions are never cached. In chat, every earlier turn still on screen is re-checked before the next question. A turn whose sources were revoked or changed is removed from the model's context, blanked in the web UI, and logged as `context_dropped`. The user sees only that earlier answers were removed, not which document caused it.
- The auditor role is read from `identities.json` on every audit request, so revoking it takes effect immediately, even in an open session. Refused attempts are logged as `audit_query_denied`.
- Switching user starts an empty history.

## Adding a source

Implement the `Source` protocol in `sources/base.py` (`search`, `can_access`, `fetch`, `changes_since`) and register it in `sources/__init__.py`. Set `container` to the project, channel, or folder so audit queries can filter on it.

## Audit trail

Each entry stores `sha256(prev_hash, seq, ts, user, event, data)`. `audit.head` holds the latest seq and hash, so deleting the newest rows is detected as well as editing or removing rows in the middle. To show tampering in the demo:

```bash
sqlite3 main_workflow/audit.db "update entries set data = replace(data, 'platform_denied', 'platform_allowed') where seq = (select max(seq) from entries where event = 'query')"
python3 -m main_workflow.cli audit verify      # or Verify chain in the Audit tab
```

Only users with `can_audit` can query the trail, and their queries are logged too.

To start a demo with an empty trail, stop the server and delete both files together. Deleting only `audit.db` leaves a stale head file, and verify then reports tampering.

```bash
rm -f main_workflow/audit.db main_workflow/audit.head
```

## Identities

| User | Role | Atlassian account | Drive | Jira / Slack (stand-ins) | Auditor |
|---|---|---|---|---|---|
| ShiHan | payments backend engineer (on-call) | Lim Shi Han | reader (to share) | PAY-101 to PAY-103; both channels | no |
| Zhao | CTO | Zhao Heng: site admin, also the system's API account | folder owner | PAY-101 to PAY-104; both channels | no |
| Ivan | security engineer | Ivan | reader (to share) | PAY-101 to PAY-104; both channels | no |
| Elson | compliance officer | Elson Chan Chong Jun | none | none | yes |
| Sheldon | finance analyst (payments reconciliation) | Sheldon | reader (to share) | `#payments` only | no |
| Terrance | external contractor (third-party vendor) | Terrance | never share | `#payments` only | no |

Confluence follows the same split: `PAYOPS` for ShiHan, Zhao, Ivan, and Sheldon; the security appendix for Ivan and Zhao only. Elson reads the audit trail but no source content, and is the only auditor.

Users without an account on a platform are denied everything there by default. Stand-in access is set in `stand_in_jira_slack/seed.json`, not here. Every user has an Atlassian account and a Google email; Slack user IDs are still empty. On the real platforms, access comes from Jira roles, Confluence space and page permissions, and Drive sharing, which do not match this table yet (see below).

# Current status: stand-ins and gaps

## Stand-in or mock

| Part | What it really is | To make it real |
|---|---|---|
| Jira | Stand-in reading a local JSON file (`stand_in_jira_slack/`) | Build `sources/jira.py`; issue-level security needs Jira Standard |
| Slack | Stand-in reading a local JSON file (`stand_in_jira_slack/`) | Build `sources/slack.py` with a bot token and real channels |
| Sign-in | A dropdown stands in for single sign-on | Fine for a hackathon; present it as a trade-off |
| Zhao | Zhao's account is also the system's API account (site admin, seeded PAYOPS) | Fine for a hackathon because Zhao, the CTO, may see everything; production would use a dedicated non-human service account |
| Atlassian permissions | All six accounts can open everything in Jira `PAY` and Confluence `PAYOPS` (checked 2026-10-13) | Restrict Jira and Confluence to match the Identities table |
| Drive users | Zhao's Google account owns the folder; ShiHan, Ivan, and Sheldon are not shared yet | `python3 gdrive/gdrive_cli.py share ShiHan Ivan Sheldon`; never share with Terrance |
| Slack user IDs | Empty; the stand-ins match users by name | Needed once real Slack exists |
| Platform console | Simulates platform admins | Correct by design: it represents the platforms, not the chat |
| Stand-in citation links | `fixture://…`, not clickable | Real sources return real URLs |

## Missing: affects the demo

1. **Confluence revocation.** The console has no Confluence access control yet. Every user now has a separate Atlassian account, so this is unblocked.
2. **The security appendix is not hidden.** ShiHan can see it and has cited it, so scenario 3 currently fails on Confluence. ShiHan now has a separate account; the page restriction is still needed. The API accepted a restriction on a test page, but enforcement against a second account is not proven yet.
3. **Real Drive revocation.** ShiHan now has a Google email; share the folder with ShiHan first.
4. **"Yesterday" in the demo question.** The seed data is dated 2026-09-28. Ask about "INC-PAY-001" instead, or re-date the seed data.
5. **No automated scenario check in the repo.** The scenarios are checked by hand with the demo flow above.

## Missing: deliverables (Phase D)

- [ ] Architecture diagram and trust-boundary diagram, with design trade-offs
- [ ] Five worked examples (setup, action, actual result)
- [ ] Presentation deck, opening with *FinTech / Aspire: The Internal Brain* as the chosen case
- [ ] Full rehearsal with timing
- [ ] Ask the organisers about page 20 of the brief (it shows healthcare criteria)
- [ ] Commit and push everything after the first commit: web UI, stand-ins, index, sync, memory, and README updates. `confluence/page_manifest.json` also changed because the restore command rewrote it. Before the repo is public, decide whether to keep the brief PDF in it and which email to use as commit author.

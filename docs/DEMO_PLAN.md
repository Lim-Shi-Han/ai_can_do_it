# Demo plan: Payment-service outage investigation

FinTech track, Aspire: **The Internal Brain**. One incident (`INC-PAY-001`) carries all five scenarios from the brief in a single live walkthrough of about 7 minutes.

Deadlines: submission **16 Oct 2026**; Demo Day **3 Nov 2026** (to be confirmed) for the top two teams.

## Flow at a glance

The flow keeps the shape of the original six-step diagram (ask → answer → update → revoke or switch user → audit) with these changes:

1. **Ask, connect, and answer are one live step.** On screen it is a single question; the steps behind it (identity, candidates, live permission check per document, cited answer) are narrated while it runs.
2. **"Revoke access or switch user" is two steps, revocation first.** Revocation (scenario 4) continues ShiHan's chat; switching to the contractor (scenario 3) starts a new one. Live order: **1 → 2 → 4 → 3 → 5**.
3. **The audit step reviews this run.** Elson inspects the questions, denials, and revocation that just happened.
4. **An access-matrix slide opens the demo**, so the judges know who should see what before anything is asked.
5. **Labels follow the brief.** Number "requirements covered" by the brief's scenarios 1–5. Ask about `INC-PAY-001`, not "yesterday's outage" (the seed story is dated 2026-09-28). Do not show the brief's Company A figures (50+ spaces, 30+ projects, 200+ channels) as if they were the demo's data.

| Step | Scenario | Who | Time |
|---|---|---|---|
| 0. Opening | — | — | 0:30 |
| 1. Ask about the incident | 1 Unified query | ShiHan (optionally Sheldon) | 1:30 |
| 2. Update and sync | 2 Data freshness | Console, then ShiHan | 1:00 |
| 3. Revoke access | 4 Live revocation | Console, then ShiHan | 1:00 |
| 4. Switch user | 3 Restricted user | Terrance, then Ivan | 1:30 |
| 5. Audit | 5 Audit inquiry | Elson | 1:30 |
| Close | Architecture and trade-offs | — | — |

Cross-cutting requirements shown along the way: answers only from permitted sources with citations and a Confirmed / Unconfirmed / Missing split (LLM safety), context assembled across four platforms, and a tamper-evident audit trail.

## Cast and access

| Persona | Role |
|---|---|
| ShiHan | Payments backend engineer (on-call) |
| Zhao | CTO; also the site admin account the system uses for API calls |
| Ivan | Security engineer |
| Sheldon | Finance analyst (payments reconciliation) |
| Terrance | External contractor (third-party vendor) |
| Elson | Compliance officer; the only auditor |

Target access on the real platforms:

| | ShiHan | Zhao | Ivan | Sheldon | Terrance | Elson |
|---|---|---|---|---|---|---|
| Confluence space `PAYOPS` | ✓ | ✓ | ✓ | ✓ | | |
| Security appendix (page restriction) | | ✓ | ✓ | | | |
| Jira `PAY-101` to `PAY-103` | ✓ | ✓ | ✓ | | | |
| `PAY-104` (issue security level) | | ✓ | ✓ | | | |
| Slack `#payment-incident-001` (private) | ✓ | ✓ | ✓ | | | |
| Slack `#payments` (public) | ✓ | ✓ | ✓ | ✓ | ✓ | |
| Drive: INC-PAY-001 metrics report | ✓ | ✓ owner | ✓ | ✓ | | |
| Audit tab | | | | | | ✓ |

Every permission layer in the brief appears in this matrix:

- **Space or project level:** Terrance has accounts but is refused all of `PAYOPS` and `PAY`; Sheldon is allowed into `PAYOPS` but refused `PAY`.
- **Page and issue level:** ShiHan is inside `PAYOPS` and `PAY` but refused the security appendix and `PAY-104`.
- **Channel membership:** Sheldon and Terrance see `#payments` only.
- **File and folder sharing:** Drive is shared per person; never with Terrance.
- **Separation of duties:** Elson reads the audit trail but no source content.

Optional extension: a restricted Confluence space `SECOPS` and Jira project `SEC` (Ivan and Zhao only) add a "same person, two spaces" contrast and match the brief's own example of a report in a space restricted to the security team.

## Step 0: Opening

- Name the case: *FinTech / Aspire: The Internal Brain*.
- Show the access matrix above.
- Put the chat (`/`) and the console (`/console`) side by side for the rest of the demo.

## Step 1: Unified query (scenario 1)

| | |
|---|---|
| **Setup** | All four sources synced. Restrictions in place. Signed in as ShiHan. |
| **Action** | ShiHan asks: *"What caused the INC-PAY-001 outage, what is the latest recovery procedure, and what work remains?"* |
| **Expected result** | One answer under Confirmed / Unconfirmed or provisional / Missing, with clickable citations from Confluence (postmortem, runbook, follow-ups), Jira (`PAY-101` to `PAY-103` status), Slack (incident thread), and Drive (metrics report). The Slack "can we just fail over now?" message is treated as discussion, not an approved step. The console's gate feed shows `PAY-104` and the security appendix were **denied** and never reached the model. |
| **Narrate** | Identity → candidates from the index → live permission check on each platform → only allowed documents become numbered sources → output check → audit entry. |

Optional variant: Sheldon asks *"What was the financial impact of INC-PAY-001, and are the numbers final?"* Expected: the Drive figure under Confirmed and the 1,240 estimate from the Confluence impact page under provisional, with no Jira or private-Slack citations.

## Step 2: Data freshness (scenario 2)

| | |
|---|---|
| **Setup** | ShiHan's chat from step 1 is still open. The runbook shows the original text (Reset rehearsal restores it). |
| **Action** | Console: **Publish runbook update** (adds the standby-region failover step). Optionally also set `PAY-101` to Done with a comment. Wait for "Sync picked up…" in the activity feed (at most 60 s) or click **Sync now**. ShiHan re-asks **the full question from step 1**. |
| **Expected result** | The new runbook version is cited with the failover step and its update time. The earlier answer is removed because the runbook version it cited is out of date. With the optional change, `PAY-101` shows as Done. |
| **Narrate** | New documents become searchable within one sync (60 s). Documents already in the index are always fetched live when answering, so their content is never stale. Permissions are checked live on every question. |

Re-ask the full question, not only the recovery part: step 3 needs an answer that cites Slack to remove.

## Step 3: Live revocation (scenario 4)

| | |
|---|---|
| **Setup** | ShiHan's chat continues; the latest answer cites Slack. |
| **Action** | Console: Slack card, **Remove** ShiHan from `#payment-incident-001`. In the same chat ShiHan asks: *"Did anyone propose failing over during the incident, and was it approved?"* |
| **Expected result** | An "earlier answers were removed" banner appears and answers that used Slack are blanked. The new answer comes from the runbook and policy only, with no Slack citations, and does not say which source was removed. The console shows the DENY decisions. |
| **Afterwards** | Give access back with **Add**, not Reset rehearsal (which clears every chat). |

Backup if Slack revocation is not ready: remove ShiHan from Jira project `PAY` and ask about remaining work instead.

## Step 4: Restricted user (scenario 3)

| | |
|---|---|
| **Setup** | Switch user to Terrance (new chat). |
| **Action** | Terrance asks: *"Show me the security review findings for INC-PAY-001."* Then switch to Ivan and ask the same question. |
| **Expected result** | Terrance gets *"I couldn't find information on that in the sources available to you."*, the same sentence as when nothing exists, so nothing reveals that restricted documents exist. Ivan gets `PAY-104` and the security appendix (plus `SECOPS` and `SEC` if built). |
| **Show** | The console access grid as live proof of the matrix. |

## Step 5: Audit inquiry (scenario 5)

| | |
|---|---|
| **Setup** | Switch user to Elson; open the Audit tab. |
| **Action** | (a) Filter user ShiHan, container `PAYOPS`, last 30 days (the brief's own example). (b) Filter document `PAY-104`. (c) **Verify chain**. Then edit one row in a terminal and verify again. |
| **Expected result** | (a) ShiHan's questions with every allow/deny decision, cited versions, answers, timestamps, and the `context_dropped` event from step 3. (b) Ivan allowed; ShiHan and Terrance denied. (c) Chain OK; after the edit, verify turns red and names the entry. |
| **Optional** | Console: **Revoke auditor role** for Elson; the next audit search is refused and logged. |

Command-line equivalents and the tamper command:

```bash
python3 -m main_workflow.cli audit query --as Elson --user ShiHan --container PAYOPS --since 30d
python3 -m main_workflow.cli audit query --as Elson --doc PAY-104
sqlite3 main_workflow/audit.db "update entries set data = replace(data, 'platform_denied', 'platform_allowed') where seq = (select max(seq) from entries where event = 'query')"
python3 -m main_workflow.cli audit verify
```

## Close

Architecture and trust-boundary diagram, then the key trade-offs:

- Polling every 60 s instead of platform webhooks or event APIs.
- The admin account (Zhao) doubles as the system's API account; production would use a dedicated non-human service account.
- A sign-in dropdown stands in for single sign-on.
- SQLite search index and audit log; a production deployment would use a proper search index and append-only storage.

## Preparation

| Item | Needed for | Owner | Priority |
|---|---|---|---|
| New Atlassian API token in `.env`; `.env` and `main_workflow/identities.json` on the DGX host | All | Jira owner | Must |
| Jira: company-managed `PAY` with Member, Administrators, and Security roles; `Security` issue security level; browse limited to project roles; `PAY-101` to `PAY-104` seeded | 1, 3, 5 | Jira owner | Must |
| Jira code: `main_workflow/sources/jira.py`, `jira/jira_cli.py` (grant, revoke, set-status, reset), console wired to it | 1, 3, 5; optional in 2 and 4 | Jira owner | Must |
| Confluence: `PAYOPS` limited to named people (remove "all licensed users"); security appendix restricted to Ivan and Zhao; confirm a paid plan | 1, 3 | Confluence owner | Must |
| Slack: real source with the memberships above and a revoke action, or keep the stand-in (labelled "stand-in" in the UI) | 1, 4 | Slack owner | Must (stand-in acceptable) |
| Drive: `python3 gdrive/gdrive_cli.py share ShiHan Ivan Sheldon`; never Terrance | 1, 3 | Drive owner | Must |
| Console: Reset rehearsal also resets Jira; access grid grouped by space, project, channel, or folder | 3, every rehearsal | Jira owner | Should |
| `SECOPS` space and `SEC` project | 3 | Confluence and Jira owners | Optional |
| Five worked examples: setup, action, and actual result with screenshots from a full rehearsal | Submission | Team | Must by 16 Oct |
| Architecture and trust-boundary diagram; presentation deck | Submission | Team | Must by 16 Oct |
| CodeBuddy or WorkBuddy chat screenshots (at least 3) from development | Submission | Team | Must: projects without this proof are not scored |

## Before each run

1. Stop the server and clear the audit trail: `rm -f main_workflow/audit.db main_workflow/audit.head`
2. Start it: `python3 -m main_workflow.web` (resets the stand-in data). Check the vLLM server is up.
3. Console: **Reset rehearsal**, then **Refresh** the access grid. It must match the access matrix above; stop and fix any mismatch.
4. Open the chat and the console side by side.

## Worked example template

Fill one in per scenario from a full rehearsal, with screenshots.

```markdown
### Scenario N: <name>
- Setup: <who, which access, data state>
- Action: <question asked or console change, with time>
- Actual result: <answer summary, citations, decisions> (screenshot: <file>)
- Audit evidence: <audit seq numbers or filter used>
```

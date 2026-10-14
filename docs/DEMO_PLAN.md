# Demo plan: INC-PAY-001, a payment outage handled live

FinTech track, Aspire: **The Internal Brain**. The incident happens during the demo: an external payment processor reports a problem, the team handles it across Jira, Slack, Google Drive, and Confluence, and the chat answers each person within their permissions. All five scenarios from the brief appear along the way.

Deadlines: submission **16 Oct 2026**; Demo Day **3 Nov 2026** (to be confirmed) for the top two teams.

## The flow at a glance

| # | Step | Who | Scenario |
|---|---|---|---|
| 1 | Processor reports timeouts in the shared Slack channel | Terrance, Zhao | — |
| 2 | Zhao opens the incident ticket **PAY-100** | Zhao | — |
| 3 | Vendor gets temporary Drive access (**ACC-41**) and uploads the timeout log | Zhao, Sheldon, Terrance | 4 (setup) |
| 4 | ShiHan diagnoses with the chat | ShiHan | **1 Unified query** |
| 5 | Rollback request **PAY-101**, approved by Ivan | ShiHan, Ivan | — |
| 6 | Recovery; Ivan writes the restricted incident report and opens **PAY-102** 🔒 and **PAY-103** | ShiHan, Ivan | 3 (setup) |
| 7 | Two-sided reconciliation (**FIN-21**) | Terrance, Sheldon | **2 Freshness** |
| 8 | Case closed; Sheldon removes the vendor's access | Zhao, Sheldon | **4 Live revocation** |
| 9 | Vendor asks for the incident report | Terrance vs Ivan (and ShiHan) | **3 Permission enforcement** |
| 10 | Compliance review of the audit trail | Elson | **5 Audit inquiry** |
| 11 | *(optional)* Runbook v2 after the failover rehearsal (**PAY-104**) | ShiHan | 2 (alternative) |

Cross-cutting requirements shown along the way: answers only from permitted sources with citations and a Confirmed / Unconfirmed / Missing split (LLM safety), context assembled across four platforms, and a tamper-evident audit trail.

## Cast

| Persona | Role | Notes |
|---|---|---|
| ShiHan | Payments backend engineer, on call | Diagnoses and carries out approved changes |
| Zhao | CTO | Opens the incident; also the admin account the system uses for API calls |
| Ivan | Security manager, the approver | Approves production changes; writes the incident report and the security assessment |
| Sheldon | Finance analyst (payments reconciliation) | Owns the vendor relationship and the reconciliation |
| Terrance | Payment processor's contact (external) | Shared Slack channel and the shared Drive folder only |
| Elson | Compliance officer | Reads Jira and comments in Confluence, changes nothing; the only auditor |

## Who can see what

**Jira** (project roles; set up by `jira/jira_cli.py`)

| | ShiHan | Zhao | Ivan | Sheldon | Terrance | Elson |
|---|---|---|---|---|---|---|
| `PAY` Payments | ✓ | ✓ | ✓ | · | · | read-only |
| `PAY` tickets at the Security level (PAY-102, PAY-94, PAY-99) | · | ✓ | ✓ | · | · | · |
| `ACC` Access Requests | · | ✓ | ✓ | ✓ | · | read-only |
| `FIN` Finance Operations | · | ✓ | · | ✓ | · | · |

**Confluence** (space roles; set up by `confluence/demo_spaces.py`)

| | ShiHan | Zhao | Ivan | Sheldon | Terrance | Elson |
|---|---|---|---|---|---|---|
| `HANDBOOK` Company Handbook | ✓ comment | ✓ admin | ✓ edit | ✓ comment | · | ✓ comment |
| `PAYOPS` Payment Operations | ✓ edit | ✓ admin | ✓ edit | · | · | ✓ comment |
| Ivan's incident report in `PAYOPS` (page restriction, created in step 6) | ✓ | ✓ | ✓ | · | · | · |
| `FINOPS` Finance Operations | · | ✓ admin | · | ✓ edit | · | · |
| `SECOPS` Security | · | ✓ admin | ✓ edit | · | · | · |

**Slack** (to set up by the Slack owner; currently the stand-in)

| Channel | Members |
|---|---|
| `#vendor-payprocessor` (shared with the processor) | Terrance, Zhao, Sheldon, ShiHan |
| `#payment-incident-001` (internal, opened in step 2) | ShiHan, Zhao, Ivan |

**Google Drive** (to set up by the Drive owner): folder `INC-PAY-001`, owned by Zhao's Google account; ShiHan can read; Sheldon can edit and share; Terrance gets **edit** access in step 3 (to upload) and loses it in step 8.

Every layer of the brief's permission models appears: space and project level (Terrance has no Jira or Confluence access; ShiHan has no `FINOPS` or `SECOPS`), page and issue level (the incident report, PAY-102), channel membership, folder sharing, and separation of duties (Elson).

## Ticket numbers

Jira numbers tickets in creation order, so the live tickets get these keys (seed noise already holds PAY-90 to PAY-99, ACC-37 to ACC-40, and FIN-17 to FIN-20):

| Key | Created in step | By | Ticket | Visible to |
|---|---|---|---|---|
| PAY-100 | 2 | Zhao | Incident: payment timeouts reported by processor; assigned to ShiHan | ShiHan, Zhao, Ivan, Elson (read) |
| ACC-41 | 3 | Sheldon | Temporary Drive access for the payment processor; signed off by Ivan and Zhao | Sheldon, Ivan, Zhao, Elson (read) |
| PAY-101 | 5 | ShiHan | Rollback change request; approved by Ivan | ShiHan, Zhao, Ivan, Elson (read) |
| PAY-102 🔒 | 6 (first) | Ivan | Security assessment: was INC-PAY-001 a breach? Concludes no | Ivan, Zhao |
| PAY-103 | 6 (second) | Ivan | Prevent recurrence: cap connection limits and validate them during rollout; assigned to ShiHan | ShiHan, Zhao, Ivan, Elson (read) |
| FIN-21 | 7 | Sheldon | Reconcile failed payments against the processor's settlement export | Sheldon, Zhao |
| PAY-104 | 11 (optional) | Ivan | Failover rehearsal; assigned to ShiHan | ShiHan, Zhao, Ivan, Elson (read) |

The flow table still shows older numbers (PAY-102 for vendor access, PAY-103 for reconciliation, PAY-104 for the security assessment, PAY-105, PAY-106); update it to this table before rehearsing.

## Step by step

### 1. Reported from outside (14:10)
- **Action:** Terrance posts in `#vendor-payprocessor`: *"authorization timeouts from your endpoint spiking since ~14:10"*. Zhao sees it.
- **Prepare:** the shared channel with the right members; the message (real Slack, or `stand_in_jira_slack/fixture_cli.py post` on the stand-in).

### 2. Incident ticket
- **Action:** Zhao opens **PAY-100** "Payment timeouts reported by processor", quoting the report, assigns ShiHan, brings in Ivan, and opens `#payment-incident-001`.
- **Prepare:** the step command that creates PAY-100 as Zhao (to build, needs the final ticket text).

### 3. Vendor gets Drive access (scenario 4 setup)
- **Action:** Zhao asks the processor for logs. Sheldon opens **ACC-41** for temporary edit access to the `INC-PAY-001` folder; Ivan and Zhao sign off in the ticket; Sheldon shares the folder with Terrance. Terrance uploads the **processor timeout log** (failed authorizations per minute from 14:10).
- **Expected:** the console's access grid shows Terrance on the Drive folder.
- **Prepare:** sharing the folder as **editor** (`gdrive_cli.py share` currently shares as reader only); the timeout log file.

### 4. Diagnose with the chat (scenario 1)
- **Action:** press **Sync now**, then ShiHan asks: *"PAY-100: what changed recently on payment-service, what does the runbook say for timeouts, and what has the processor reported?"*
- **Expected:** one answer citing all four platforms: PAY-100 (Jira), the processor's report and the 14:07 rollout notice (Slack), the processor timeout log (Drive), and the recovery runbook (Confluence: connection saturation, pause rollouts and roll back after approval). Likely cause: the 14:07 rollout.
- **Note:** the search uses up to 6 keywords, so "timeouts" and "processor" are currently dropped from this question; raise the limit or check that the Slack and Drive items are still found.

### 5. Rollback approved
- **Action:** ShiHan opens rollback change request **PAY-101** and asks Ivan for approval on PAY-100 and in `#payment-incident-001`. Ivan approves in both places. ShiHan pauses rollouts and starts the rollback at 14:37.
- **Matches:** the runbook (step 4: ask the approver) and the Company Handbook's incident response policy (no production change without the approver's written approval).

### 6. Recovery and the incident report (scenario 3 setup)
- **Action:** at 15:02 ShiHan reports that payments have recovered. PAY-101 is done and PAY-100 resolved. Ivan writes the **incident report** in `PAYOPS`, restricted to ShiHan, Zhao, and Ivan, and opens **PAY-102** 🔒 (security assessment: no breach) and **PAY-103** (prevent recurrence, assigned to ShiHan).
- **Show:** the console's access grid. Elson can read `PAYOPS` but not the report (page level); ShiHan can read `PAY` but not PAY-102 (issue level).
- **Rule:** the incident report must **not** name PAY-102 or its title. An answer that repeats a ticket the asker cannot see is replaced by the "couldn't find information" sentence. Write "a separate security assessment is tracked by the security team".
- **Prepare:** the step command that creates the report as Ivan (Ivan's own token) and restricts it immediately (to build, needs the final text).

### 7. Two-sided reconciliation (scenario 2)
- **Action:** Terrance uploads the **settlement export** and asks: *"Reconcile the failed payments for INC-PAY-001."* The answer reconciles only the processor's side and lists Company A's payment records as **missing**. Terrance asks Sheldon in `#vendor-payprocessor`; Sheldon uploads the **internal payment ledger extract**, replies, and tracks the work in **FIN-21**. Press **Sync now**. Terrance asks again.
- **Expected:** both files are found and the answer gives the reconciliation: **1,312 timed-out attempts, 214 retried successfully, no duplicate charges**.
- **Shows:** a file added minutes ago changes the answer within one sync (60 s).

### 8. Case closed, access removed (scenario 4)
- **Action:** with PAY-100 and FIN-21 closed, Zhao notices the processor can read Company A's internal ledger extract: *"the processor doesn't need our folder any more."* Sheldon **unshares** Terrance (console: Drive **Unshare**) and closes ACC-41 ("access revoked, case closed"). Terrance asks a follow-up in the same chat.
- **Expected:** nothing from Drive, and the earlier reconciliation answer is removed from the chat ("earlier answers were removed"), without saying which source caused it.

### 9. Vendor asks for the report (scenario 3)
- **Action:** Terrance asks: *"Was this a security breach? Show me the incident report for INC-PAY-001."* Ivan asks the same question.
- **Expected:** Terrance gets the neutral "couldn't find information" sentence, with no hint that the report exists. Ivan gets the incident report and PAY-102 (no breach).
- **Recommended addition:** ShiHan asks too, and gets the report but **not** PAY-102. Terrance has no access to `PAYOPS` or `PAY` at all, so Terrance alone only shows space and project level; ShiHan shows the page and issue levels.

### 10. Compliance review (scenario 5)
- **Action:** Elson opens the Audit tab: Terrance's Drive access before and after the revocation against ACC-41, and Terrance's denied request for the incident report. Then **Verify chain**. Optionally, edit one row in a terminal and verify again (it turns red), or revoke Elson's auditor role in the console.
- **Commands:**

```bash
python -m main_workflow.cli audit query --as Elson --user Terrance --since 1d
python -m main_workflow.cli audit verify
```

### 11. Runbook v2 (optional, scenario 2 alternative)
- **Action:** Ivan opens **PAY-104** (failover rehearsal). Afterwards ShiHan publishes the runbook with the approved failover step: console **Publish runbook update** (published as ShiHan). Ask about the recovery procedure again.
- **Expected:** the answer cites runbook version 2 with the standby-region step.

## Preparation

| Item | Owner | Status |
|---|---|---|
| Jira: projects `PAY`, `ACC`, `FIN`, roles, the Security level, 18 noise tickets | Jira | ✅ Done |
| Jira source in the app; console Jira buttons on real Jira | Jira | ✅ Done |
| Confluence: four spaces, roles, 17 pages by their owners, old pages in the trash | Confluence | ✅ Done |
| Confluence source reads all four spaces; runbook v1 and v2 tooling | Confluence | ✅ Done |
| Permission checks run in parallel; real access verified with each person's own token | — | ✅ Done |
| Live step commands for the Jira tickets (steps 2, 3, 5, 6, 7, 8, 11) | Jira | ⬜ Needs the final ticket text |
| Ivan's incident report, created and restricted live (step 6) | Confluence | ⬜ Needs the final text |
| Flow table renumbered to the keys above; Ivan's role name matching `identities.json` ("security engineer" there) | Flow | ⬜ |
| Slack: `#vendor-payprocessor` (shared) and `#payment-incident-001`, the step messages | Slack | ⬜ |
| Drive: folder sharing as above, sharing Terrance as **editor**, the three files (timeout log, settlement export, ledger extract) | Drive | ⬜ |
| Local run: Drive key file and folder ID in `.env`; the LLM endpoint (see below) | Whoever demos | ⬜ |
| Five worked examples with screenshots from a full rehearsal | Team | ⬜ by 16 Oct |
| Architecture and trust-boundary diagram; deck | Team | ⬜ by 16 Oct |
| CodeBuddy or WorkBuddy chat screenshots (at least 3) | Team | ⬜ by 16 Oct, required for scoring |

## Running it locally

1. `.env` has the Jira keys (`JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY=PAY,ACC,FIN`), the persona tokens (`JIRA_TOKEN_SHIHAN`, `JIRA_TOKEN_IVAN`, `JIRA_TOKEN_SHELDON`), and `CONFLUENCE_SPACE_KEYS=HANDBOOK,PAYOPS,FINOPS,SECOPS`. Confluence uses the Jira credentials.
2. Drive: `gdrive/service_account.json` (not in Git) plus `GOOGLE_SERVICE_ACCOUNT_FILE` and `GDRIVE_FOLDER_ID` in `.env`; without them the app skips Drive.
3. LLM: the app calls `http://127.0.0.1:8500/v1` (model `qwen-spec-poc`). Tunnel to the DGX first: `ssh -L 8500:localhost:8500 <dgx-host>`. To use another OpenAI-compatible server, set `VLLM_BASE_URL` and `VLLM_MODEL` in the terminal; they are not read from `.env`.
4. `main_workflow/identities.json` (not in Git; copy `identities.example.json` and fill in the real emails, or get it from a teammate).

## Before each rehearsal

1. **Jira:** `python jira/jira_cli.py rebuild --yes` at least 30 minutes before. It removes the previous run's tickets so the live tickets get PAY-100, ACC-41, and FIN-21 again. Wait until `python jira/jira_cli.py access` matches the table above.
2. **Confluence:** delete the previous run's incident report (command to come), then `python confluence/confluence_cli.py restore-runbook`.
3. **Drive:** remove the previous run's uploads; make sure Terrance is not shared.
4. Sign in once to Jira and Confluence with each persona account; Jira's permission check can lag until an account has signed in.
5. Clear the audit trail and start the app (this also resets the Slack stand-in):

```bash
rm -f main_workflow/audit.db main_workflow/audit.head
python -m main_workflow.web
```

6. Console: **Refresh** the access grid and check it against the tables above. Open the chat (`/`) and the console (`/console`) side by side.
7. Remember **Sync now** before steps 4, 7 (second question), and 9.

## Worked example template

Fill one in per scenario from a full rehearsal, with screenshots.

```markdown
### Scenario N: <name> (flow step <n>)
- Setup: <who, which access, data state>
- Action: <question asked or change made, with time>
- Actual result: <answer summary, citations, decisions> (screenshot: <file>)
- Audit evidence: <audit seq numbers or filter used>
```

# Demo plan: INC-PAY-001, a payment outage handled live

FinTech track, Aspire: **The Internal Brain**. The incident happens during the demo: an external payment processor reports a problem, the team handles it across Jira, Slack, Google Drive, and Confluence, and the chat answers each person within their permissions. All five scenarios from the brief appear along the way.

Deadlines: submission **16 Oct 2026**; Demo Day **3 Nov 2026** (to be confirmed) for the top two teams.

## The flow at a glance

| # | Step | Who | Scenario |
|---|---|---|---|
| 1 | Processor reports timeouts in the shared Slack channel | Terrance, Zhao | — |
| 2 | Zhao opens the incident ticket **PAY-100** | Zhao | — |
| 3 | Vendor gets temporary Drive access (**ACC-41**) from Zhao and uploads the timeout log | Sheldon, Zhao, Terrance | 4 (setup) |
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

**Google Drive** (folder sharing; set up by `gdrive/demo_drive.py seed`). Zhao's Google account owns the folders; each person owns the files they wrote.

| | ShiHan | Zhao | Ivan | Sheldon | Terrance | Elson |
|---|---|---|---|---|---|---|
| `Company A/Payments Engineering` | ✓ edit | ✓ owner | ✓ edit | · | · | · |
| `Company A/Finance` | one file (comment) | ✓ owner | · | ✓ edit | · | · |
| `Company A/Security` | · | ✓ owner | ✓ edit | · | · | · |
| `Company A/Vendors/PayProcessor` | ✓ view | ✓ owner | ✓ comment | ✓ edit | · | · |
| `…/PayProcessor/INC-PAY-001 shared with PayProcessor` | ✓ view | ✓ owner | ✓ comment | ✓ edit | ✓ edit, steps 3 to 8 only | · |

The processor folder is the only folder shared outside Company A, and it is empty before step 3. 15 standing files sit in the other folders as noise; none of them is found by the demo questions.

Every layer of the brief's permission models appears: space and project level (Terrance has no Jira or Confluence access; ShiHan has no `FINOPS` or `SECOPS`), page and issue level (the incident report, PAY-102), channel membership, folder and file sharing (the processor folder; one Finance file shared with ShiHan alone), external sharing (Terrance), and separation of duties (Elson).

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
- **Action:** Zhao asks the processor for logs. Sheldon opens **ACC-41** for temporary edit access to the folder `INC-PAY-001 shared with PayProcessor`; Ivan and Zhao sign off in the ticket; Zhao shares the folder with Terrance as editor. Terrance uploads the **processor timeout log**: requests and timeouts per minute from 14:00, exported at 14:26 (387 timeouts since 14:10, rising).
- **Commands:**

```bash
python gdrive/gdrive_cli.py share Terrance --role editor   # Zhao grants access (console: Drive, Terrance, Editor, Share)
python gdrive/demo_drive.py upload 3                       # Terrance uploads with his own Google sign-in (console: Step 3 upload)
```

- **Expected:** the console's access grid shows Terrance on the folder, and Drive shows the file with Terrance as owner. Optional: run the upload before the share to show Drive refusing it.
- **Note:** share as **Editor**: a viewer cannot upload, and Drive refuses the upload.

### 4. Diagnose with the chat (scenario 1)
- **Action:** press **Sync now**, then ShiHan asks: *"PAY-100: what changed recently on payment-service, what does the runbook say for timeouts, and what has the processor reported?"*
- **Expected:** one answer citing all four platforms: PAY-100 (Jira), the processor's report and the 14:07 rollout notice (Slack), the processor timeout log (Drive), and the recovery runbook (Confluence: connection saturation, pause rollouts and roll back after approval). Likely cause: the 14:07 rollout.
- **Note:** the search uses up to 6 keywords, so "timeouts" and "processor" are currently dropped from this question. The Drive timeout log is still found, because it names the `payment-service` endpoint (checked on the real Drive); check that the Slack items are found too, or raise the limit.

### 5. Rollback approved
- **Action:** ShiHan opens rollback change request **PAY-101** and asks Ivan for approval on PAY-100 and in `#payment-incident-001`. Ivan approves in both places. ShiHan pauses rollouts and starts the rollback at 14:37.
- **Matches:** the runbook (step 4: ask the approver) and the Company Handbook's incident response policy (no production change without the approver's written approval).

### 6. Recovery and the incident report (scenario 3 setup)
- **Action:** at 15:02 ShiHan reports that payments have recovered. PAY-101 is done and PAY-100 resolved. Ivan writes the **incident report** in `PAYOPS`, restricted to ShiHan, Zhao, and Ivan, and opens **PAY-102** 🔒 (security assessment: no breach) and **PAY-103** (prevent recurrence, assigned to ShiHan).
- **Show:** the console's access grid. Elson can read `PAYOPS` but not the report (page level); ShiHan can read `PAY` but not PAY-102 (issue level).
- **Rule:** the incident report must **not** name PAY-102 or its title. An answer that repeats a ticket the asker cannot see is replaced by the "couldn't find information" sentence. Write "a separate security assessment is tracked by the security team".
- **Command:** console **Step 6: Ivan publishes the incident report**, or `python confluence/demo_spaces.py incident-report`. Ivan publishes it with his own token and restricts viewing and editing to ShiHan, Zhao, and Ivan; the command then prints who Confluence lets open it. The text is in `confluence/demo_spaces.json` (`incident_report`); it gives the timeline, root cause, provisional impact, and follow-ups, and says a separate security assessment is tracked by the security team.

### 7. Two-sided reconciliation (scenario 2)
- **Action:** Terrance uploads the **settlement export** (`demo_drive.py upload 7 Terrance`), presses **Sync now**, and asks: *"Reconcile the failed payments for INC-PAY-001."* The answer reconciles only the processor's side (1,312 failed with no answer, none settled; the processor cannot tell which later payments were retries) and lists Company A's payment records as **missing**. Terrance asks Sheldon in `#vendor-payprocessor`; Sheldon shares a copy of Company A's payment records made for the processor (`demo_drive.py upload 7 Sheldon`), replies, and tracks the work in **FIN-21**. Press **Sync now**. Terrance asks again.
- **Expected:** the processor's two files and Company A's copy are found, and the answer gives the reconciliation: **1,312 timed-out attempts, 214 retried successfully, no duplicate charges** (87 late approvals had their card holds released).
- **Shows:** a file added minutes ago changes the answer within one sync (60 s).
- **Note:** Sheldon's Google account cannot sign in yet, so Zhao uploads his copy and Drive shows Zhao as its owner (`uploaded_by` in `gdrive/demo_drive.json`).

### 8. Case closed, access removed (scenario 4)
- **Action:** with PAY-100 and FIN-21 closed, Zhao notices the processor can still open Company A's payment records: *"the processor doesn't need our folder any more."* Sheldon **unshares** Terrance (`python gdrive/gdrive_cli.py unshare Terrance`, or console: Drive **Unshare**) and closes ACC-41 ("access revoked, case closed"). Terrance asks a follow-up in the same chat.
- **Expected:** nothing from Company A's files in Drive, and the earlier reconciliation answer is removed from the chat ("earlier answers were removed"), without saying which source caused it. Terrance still sees the two files he uploaded himself: in personal Google accounts the uploader owns the file. Company A's payment records, and with them the 214 figure, are gone.

### 9. Vendor asks for the report (scenario 3)
- **Action:** Terrance asks: *"Was this a security breach? Show me the incident report for INC-PAY-001."* Ivan asks the same question.
- **Expected:** Terrance gets the neutral "couldn't find information" sentence, with no hint that the report exists. Ivan gets the incident report and PAY-102 (no breach). Terrance's own Drive files use the processor's case number (PP-58213), not INC-PAY-001, so they do not match this question.
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
| Ivan's incident report, created and restricted live (step 6): command and console button; checked that Ivan, ShiHan, and Zhao get it in step 9 and Elson, Sheldon, and Terrance are denied | Confluence | ✅ Done (review the wording in `demo_spaces.json`) |
| Flow table renumbered to the keys above; Ivan's role name matching `identities.json` ("security engineer" there) | Flow | ⬜ |
| Slack: `#vendor-payprocessor` (shared) and `#payment-incident-001`, the step messages | Slack | ⬜ |
| Drive: `Company A` folders and sharing as above, 15 standing files by their owners, the old metrics report removed | Drive | ✅ Done |
| Drive: the three demo files (timeout log, settlement export, payment records copy), uploaded as their owners by `demo_drive.py upload`; steps 3 to 9 rehearsed on the real Drive (gate only, no LLM) | Drive | ✅ Done |
| Drive: a Google account that can sign in for Sheldon (until then Zhao uploads his files) | Drive | ⬜ |
| Console: Drive **Share** with a role, the three demo upload buttons, and the step 6 report button | — | ✅ Done |
| Local run: Drive files from Shi Han (`gdrive/SETUP.md`); the LLM endpoint (see below) | Whoever demos | ⬜ |
| Five worked examples with screenshots from a full rehearsal | Team | ⬜ by 16 Oct |
| Architecture and trust-boundary diagram; deck | Team | ⬜ by 16 Oct |
| CodeBuddy or WorkBuddy chat screenshots (at least 3) | Team | ⬜ by 16 Oct, required for scoring |

## Running it locally

0. Python environment: `uv sync` once, then activate `.venv` in each terminal (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS or Linux). See `main_workflow/README.md`.
1. `.env` has the Jira keys (`JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY=PAY,ACC,FIN`), the persona tokens (`JIRA_TOKEN_SHIHAN`, `JIRA_TOKEN_IVAN`, `JIRA_TOKEN_SHELDON`), and `CONFLUENCE_SPACE_KEYS=HANDBOOK,PAYOPS,FINOPS,SECOPS`. Confluence uses the Jira credentials.
2. Drive: follow `gdrive/SETUP.md`. You need `gdrive/service_account.json`, `gdrive/oauth_client.json`, and the persona sign-ins in `gdrive/tokens/` from Shi Han (none of them in Git), plus `GOOGLE_SERVICE_ACCOUNT_FILE` and `GDRIVE_FOLDER_ID` in `.env`. Without the key file and folder ID the app skips Drive; without the sign-ins the demo uploads fail.
3. LLM: the app calls `VLLM_BASE_URL` with `VLLM_MODEL`, read from `.env` (see `.env.example`: `http://127.0.0.1:8038/v1`, `deepseek-v4-flash`); a variable set in the terminal wins. Open the port mapping to the model server first, then check it answers: `curl http://127.0.0.1:8038/v1/models` should list the model. Otherwise every question and ticket draft fails with "No connection could be made because the target machine actively refused it".
4. `main_workflow/identities.json` (not in Git; copy `identities.example.json` and fill in the real emails, or get it from a teammate).

## Before each rehearsal

1. **Jira:** `python jira/jira_cli.py rebuild --yes` at least 30 minutes before. It removes the previous run's tickets so the live tickets get PAY-100, ACC-41, and FIN-21 again. Wait until `python jira/jira_cli.py access` matches the table above.
2. **Confluence:** `python confluence/demo_spaces.py incident-report --remove` (deletes the previous run's report for good, so the title is free again), then `python confluence/confluence_cli.py restore-runbook`. Console **Reset rehearsal** does both.
3. **Drive:** `python gdrive/demo_drive.py reset --yes` (removes Terrance and deletes the previous run's uploads as their owners), then `python gdrive/demo_drive.py check`. Persona sign-ins expire after 7 days, so the day before, run `python gdrive/gdrive_cli.py check --as` for Zhao, ShiHan, Ivan, and Terrance.
4. Sign in once to Jira and Confluence with each persona account; Jira's permission check can lag until an account has signed in.
5. Clear the audit trail and start the app (this also resets the Slack stand-in):

```bash
rm -f main_workflow/audit.db main_workflow/audit.head
python -m main_workflow.sync --once --full   # rebuild the search index from what is in each platform now
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

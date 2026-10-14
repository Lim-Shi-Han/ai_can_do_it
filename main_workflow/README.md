# Development plan

| Phase | Work | Status |
|---|---|---|
| A | `sources/base.py`, `audit.py`, `gate.py`, `pipeline.py`, plus the Confluence source: the full loop working on Confluence only | ✅ Done |
| B | Jira, Slack, and Drive sources against the interface | 🟡 In progress: Drive and Slack done; Jira running on a stand-in (`stand_in_jira_slack/`) |
| C | `index.py`, `sync.py`, `memory.py`: scenarios 2 and 4 | ✅ Done (live freshness rehearsal still to run) |
| D | Run the demo script end to end, then the architecture and trust-boundary diagrams | 🟡 In progress: demo flow runs in the web UI; rehearsal, diagrams, and worked examples to do |
| E (optional) | A small web UI with a user switcher, replacing the command-line chat | ✅ Done (`python3 -m main_workflow.web`) |

# To-do list

**Sources (Phase B)**
- [ ] Jira source `sources/jira.py`: project `PAY`, issues PAY-101 to PAY-104 labelled `INC-PAY-001`, PAY-104 at the Security issue-security level
- [x] Slack source `sources/slack.py` and the `/brain` bot `slack_bot.py` (see Slack below)
- [ ] Slack workspace: create the Brain app (see Slack below), then follow `slack_demo/README.md` to log in Zhao and ShiHan and run `slack_cli.py reset`, which creates the channels, sets members, invites the bot, and posts the threads
- [x] Stand-in Jira and Slack sources in `stand_in_jira_slack/` for rehearsals
- [ ] Swap the Jira stand-in for the real source in `sources/__init__.py` (Slack switches itself once `SLACK_BOT_TOKEN` is set)
- [ ] Confirm the Jira keys, Slack channel, and Drive file title used in `confluence/seed_pages.json` with the source owners

**Accounts and permissions**
- [x] Jira and Confluence on paid plans, so pages and issues can be restricted (enforcement checked with each person's own token, 2026-10-14)
- [x] Restrict Jira (`PAY`, `ACC`, `FIN`) and Confluence (`HANDBOOK`, `PAYOPS`, `FINOPS`, `SECOPS`) to match the Identities table below
- [ ] Step 6: create Ivan's incident report live in `PAYOPS`, restricted to ShiHan, Zhao, and Ivan (needs the final text)
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

When Slack is configured, the server also runs the Slack bot (see Slack below), and the console's Slack card changes real channel membership through `slack_demo/slack_cli.py`.

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
python3 -m main_workflow.cli reset                     # base state for every platform; see Reset below

python3 -m main_workflow.cli audit query --as Elson --user ShiHan --container PAYOPS --since 30d
python3 -m main_workflow.cli audit query --as Elson --doc 65887     # who retrieved the runbook page
python3 -m main_workflow.cli audit verify
```

## Files

| File | Purpose |
|---|---|
| `sources/base.py` | The interface every platform implements: `search`, `can_access`, `fetch`, `changes_since`. |
| `sources/confluence.py` | Confluence source for the spaces in `CONFLUENCE_SPACE_KEYS` (`HANDBOOK`, `PAYOPS`, `FINOPS`, `SECOPS`). Reuses the client in `confluence/confluence_cli.py` and adds search and a live per-user permission check; each page is labelled with its own space. |
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

## Slack

Install once with `pip install slack_bolt`. Until `SLACK_BOT_TOKEN` is set, everything runs on the Slack stand-in.

**Setup.** At <https://api.slack.com/apps>, choose *Create New App → From a manifest*, pick the workspace, and paste:

```yaml
display_information:
  name: Internal Brain
features:
  bot_user:
    display_name: brain
  slash_commands:
    - command: /brain
      description: Ask the Internal Brain. Only you see the answer.
      usage_hint: what is the status of INC-PAY-001?
oauth_config:
  scopes:
    bot: [channels:history, groups:history, channels:read, groups:read, users:read, commands]
settings:
  socket_mode_enabled: true
  interactivity:
    is_enabled: true
  event_subscriptions:
    bot_events: [message.channels, message.groups, member_joined_channel, member_left_channel]
```

1. *Install to Workspace*, then copy the *Bot User OAuth Token*.
2. *Basic Information → App-Level Tokens → Generate*, with the scope `connections:write`.
3. Add both to `.env`:

   ```text
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   ```

4. Fill in `slack_user_id` for each user in `identities.json`.
5. Set up the demo channels and threads with `slack_demo/slack_cli.py` (see `slack_demo/README.md`). It also invites the bot. For any other channel, `/invite @brain`; the Brain never reads DMs.

**Behaviour**

- `/brain <question>` answers privately, because the answer is scoped to the asker and others in the channel may have less access. `/brain reset` clears the asker's chat. The user comes from Slack's own user ID, not the demo dropdown; unlinked accounts are refused and logged as `unknown_user`.
- The app has no `chat:write` scope and replies only through the slash command's private response. Answer text is escaped, so source content cannot trigger `@channel` pings or disguised links.
- Message, edit, and delete events update the index within seconds. The 60 s poll stays as the backup for missed events.
- Members joining or leaving a channel are logged as `permission_change` under the affected user. Access is still checked live on every question; the entry only records when it changed.
- Trade-offs: access is channel membership, which is stricter than Slack itself (any full member can read a public channel). Bot tokens cannot call `search.messages`, so Slack is searched through the index only.

## Actions: creating Jira tickets

The Brain can create Jira tickets through a real tool call, in the web chat and with `/brain` (`main_workflow/actions.py`):

1. **Router.** A request that asks for a ticket ("create / open / raise / log … ticket / issue / Jira") is offered the `create_jira_ticket` tool. Questions never are: offered the tool on every question, the model drafted tickets for questions about existing tickets, and its answers got worse.
2. **Tool call.** The model decides whether to call the tool, and fills in project, summary, description, assignee, labels, and the sources it used, from the same permission-checked sources as an answer. If it answers in text instead, that is a normal answer.
3. **Draft.** Code validates the call and asks Jira, live, whether the asker may create tickets in that project. If not, the asker is told which projects they may use (Elson and Terrance: none). Otherwise the asker sees the exact draft and clicks **Create in Jira** or **Cancel**. The draft stays on the server and is used once; only its owner can confirm it, within 15 minutes.
4. **Create.** Plain code creates the ticket after checking Jira's permission again, with the asker as reporter, using the system's Jira account. The description lists the sources and says who confirmed it.

The model never calls Jira. Each step is audited: `action_proposed`, `action_executed`, `action_cancelled`, or `action_denied`. The command line (`cli.py ask`) offers no tools. Slack's buttons need **Interactivity** on in the Slack app (see the manifest above). Trade-off: production would create the ticket with the asker's own Jira login (OAuth) instead of the system account plus a permission check.

## Reset

`python -m main_workflow.cli reset`, or **Reset rehearsal** in the console, puts every configured platform back to the demo's base state (`main_workflow/rehearsal.py`):

- **Jira:** projects holding tickets created during a demo are rebuilt, so the next tickets get PAY-100, ACC-41, and FIN-21 again (Jira never reuses a key; this takes minutes per project). Then roles, statuses, and comments go back to the seed.
- **Slack:** the demo channels keep their members and the bot, and every message is deleted. The demo posts its steps with `slack_demo/slack_cli.py play`.
- **Confluence and Drive**, when configured: the original runbook, and Drive re-shared with ShiHan.

With the web server running, the reset goes through it: it also re-syncs the search index and clears every web and `/brain` chat. With no server running, it also deletes the audit trail and search index, so stop the server first for a clean audit trail. The console never clears the audit trail.

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

Confluence spaces (space roles, set by `confluence/demo_spaces.py`):

| Space | ShiHan | Zhao | Ivan | Elson | Sheldon | Terrance |
|---|---|---|---|---|---|---|
| `HANDBOOK` Company Handbook | comment | admin | edit | comment | comment | · |
| `PAYOPS` Payment Operations | edit | admin | edit | comment | · | · |
| `FINOPS` Finance Operations | · | admin | · | · | edit | · |
| `SECOPS` Security | · | admin | edit | · | · | · |

Ivan's incident report (created live in step 6) is restricted further to ShiHan, Zhao, and Ivan. Elson can read Jira `PAY` and `ACC` and comment in Confluence but change nothing, and is the only auditor.

Users without an account on a platform are denied everything there by default. Stand-in access is set in `stand_in_jira_slack/seed.json`, not here. Every user has an Atlassian account and a Google email; Slack user IDs are still empty. On the real platforms, access comes from Jira roles, Confluence space roles and page restrictions, and Drive sharing. Jira and Confluence match these tables (checked 2026-10-14); Drive sharing does not yet (see below).

# Current status: stand-ins and gaps

## Stand-in or mock

| Part | What it really is | To make it real |
|---|---|---|
| Slack | Stand-in reading a local JSON file (`stand_in_jira_slack/`) | Build `sources/slack.py` with a bot token and real channels |
| Sign-in | A dropdown stands in for single sign-on | Fine for a hackathon; present it as a trade-off |
| Zhao | Zhao's account is also the system's API account (site admin, seeded PAYOPS) | Fine for a hackathon because Zhao, the CTO, may see everything; production would use a dedicated non-human service account |
| Drive users | Zhao's Google account owns the folder; ShiHan, Ivan, and Sheldon are not shared yet | `python3 gdrive/gdrive_cli.py share ShiHan Ivan Sheldon`; never share with Terrance |
| Slack user IDs | Empty; the stand-ins match users by name | Needed once real Slack exists |
| Platform console | Simulates platform admins | Correct by design: it represents the platforms, not the chat |
| Stand-in citation links | `fixture://…`, not clickable | Real sources return real URLs |

## Missing: affects the demo

1. **Confluence access in the console.** The console has no Confluence access controls; the demo revokes on Drive, so none are needed. Change space roles with `confluence/demo_spaces.py` or in Confluence.
2. **Ivan's incident report (step 6).** Created live in `PAYOPS` and restricted to ShiHan, Zhao, and Ivan; the command that creates it needs the final text. Restrictions are enforced (checked 2026-10-14: a restricted test page returned "not found" to ShiHan and Sheldon with their own tokens).
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

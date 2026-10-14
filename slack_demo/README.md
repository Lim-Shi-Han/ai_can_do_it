# Slack demo

`slack_cli.py` sets up the real Slack side of the INC-PAY-001 demo flow and resets it between rehearsals. It creates the channels, sets their members, invites the Brain's bot, and posts each step's messages as the demo users themselves. The platform console's Slack card and **Reset rehearsal** call it too.

Tokens are needed for everyone who posts: **Zhao** (also the admin who creates channels and manages members), **Terrance**, **Sheldon**, **ShiHan**, and **Ivan**.

Tokens are saved straight into `.env`, which Git ignores. Never paste them into chat or commit them. The Brain itself never uses these tokens; it reads Slack through its own read-only bot.

## One-time setup

1. **Make Zhao a workspace admin**, so Zhao can remove members. As the workspace owner (Terrance), open *Admin → Manage members*, then Zhao → *⋯ → Change account type → Workspace Admin*.
2. **Delete any demo channels made by hand.** If someone else already created `#payment-incident-001` or `#payments`, delete them (channel name → *Settings → Delete this channel*). Zhao must create them, and an archived channel keeps its name.
3. **A separate app**, which keeps the Brain's own app read-only. At <https://api.slack.com/apps>, choose *Create New App → From a manifest*, pick Company A, and paste on the YAML tab:

   ```yaml
   display_information:
     name: Company A Demo Tools
   oauth_config:
     redirect_urls: [https://localhost/slack-login]
     scopes:
       user: [chat:write, channels:read, groups:read, channels:history, groups:history, channels:write, groups:write]
   ```

4. **Credentials.** Under *Basic Information → App Credentials*, copy the Client ID and Client Secret into `.env`:

   ```text
   SLACK_DEMO_CLIENT_ID=...
   SLACK_DEMO_CLIENT_SECRET=...
   ```

5. **Log in Zhao, Terrance, Sheldon, ShiHan, and Ivan.** For each person, use a browser signed in to Slack as that person:

   ```bash
   python3 slack_demo/slack_cli.py login Zhao                # open the printed link, click Allow
   python3 slack_demo/slack_cli.py login Zhao "<address>"    # paste the address the browser landed on
   ```

   After *Allow*, the browser says the localhost page can't be reached. That is expected: the address bar holds a one-time code, valid for 10 minutes. The script refuses a code approved by the wrong person.

6. **First reset**, with the web server running. It needs `SLACK_BOT_TOKEN` in `.env` (see the Slack section of `main_workflow/README.md`):

   ```bash
   python3 slack_demo/slack_cli.py reset
   ```

## Commands

| Command | What it does |
|---|---|
| `reset` | Creates the channels below if missing, sets exactly those members plus the bot, deletes all messages, and posts steps 1–3. The console's **Reset rehearsal** runs this. |
| `play 5` | Posts a later step's messages (5, 6, 7, or 8) at its point in the demo. |
| `status` | Who is in each demo channel. |
| `revoke ShiHan payment-incident-001` | Removes a user from a channel. The console's Slack **Remove** button runs this. |
| `grant ShiHan payment-incident-001` | Adds them back. The console's **Add** button runs this. |

| Channel | Type | Members |
|---|---|---|
| `#vendor-payprocessor` | private; stands in for a Slack Connect channel shared with the processor (Slack Connect needs a paid plan) | Terrance, Zhao, Sheldon, ShiHan |
| `#payment-incident-001` | private | Zhao, ShiHan, Ivan |
| `#payments` | public | Zhao, ShiHan, Ivan, Sheldon |

The messages for each step are in `STEPS` in `slack_cli.py`. Nothing in `#vendor-payprocessor` may say "incident", "report", "security", "breach", or INC-PAY-001: Terrance's step 9 question would find it and he would get an answer instead of the neutral reply.

Run `reset` while the web server is running, so the bot's events drop the deleted threads from the index. If the server was off, run `python3 -m main_workflow.sync --once --full` afterwards.

Slack stamps each message with the time it was posted, so citation cards show the posting time. The messages carry the incident's own clock times (14:07, 14:10, 14:37, 15:02) in their text.

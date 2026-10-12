# Confluence hackathon fixture

Target: `https://hackathontencent.atlassian.net/wiki/spaces/PAYOPS/overview`

This folder contains eight fictional pages for incident `INC-PAY-001`. The seed story is dated 2026-09-28 and assumes a 2026-09-29 demo. Agree on any date change with the Jira, Slack, and Drive owners before publishing. The Jira keys, Slack channel, and Drive file title in `seed_pages.json` are placeholders until the other owners confirm them.

## Publish the pages

1. Create an Atlassian API token at <https://id.atlassian.com/manage-profile/security/api-tokens>. This script supports a standard token through the site URL. If you create a scoped token, also set `ATLASSIAN_CLOUD_ID` so requests use Atlassian's scoped-token gateway. The account needs permission to create and edit pages in `PAYOPS`.
2. Create a `.env` file in the repository root with your Slack/Atlassian account email and the token. `.env` is ignored by Git. Keep the token out of chat:

   ```text
   ATLASSIAN_EMAIL=your-atlassian-email@example.com
   ATLASSIAN_API_TOKEN=your-new-token
   ```

   The script reads only these values and does not execute the `.env` file as shell code. Environment variables also work and take precedence over `.env` values.

3. From the repository root, run:

   ```bash
   python3 confluence/confluence_cli.py preview
   python3 confluence/confluence_cli.py check
   python3 confluence/confluence_cli.py seed
   ```

`seed` creates only missing titles; running it again does not overwrite edited pages. It writes `confluence/page_manifest.json` with page IDs, URLs, versions, and update times. The manifest contains only the eight scenario pages and can be shared with the retrieval teammate; it contains no token.

Inspect a page as clean text and citation metadata with `python3 confluence/confluence_cli.py read PAGE_ID`. Refresh the manifest with `python3 confluence/confluence_cli.py list`. The manifest is a snapshot of IDs, URLs, and versions; the connector must fetch current content when answering.

## Freshness demo

Keep the runbook at version 1 until the live demo. Then run:

```bash
python3 confluence/confluence_cli.py update-runbook
python3 confluence/confluence_cli.py list
```

The update adds the standby-region failover step and increments the Confluence page version. The retrieval system should observe the new version, update time, and text within its stated sync window. The command updates only the runbook; it never resets the other pages.

After the demo, `python3 confluence/confluence_cli.py restore-runbook` republishes the original text. Confluence cannot delete the current version, so this creates a new version with the original content. Both commands do nothing when the page already shows the target text.

## Later permission demo

Confluence Free cannot restrict individual pages. The security appendix currently contains fictional content and is visible to all users of this site. After upgrading, restrict it to the security user or group and confirm that the contractor cannot view it. The assistant's retrieval layer must check the actual user's current Confluence access before passing text to the model.

## API handoff

The CLI uses Confluence REST API v2 to look up the `PAYOPS` space, list its pages, fetch page bodies in storage format, create pages, and update the runbook. The retrieval teammate can reuse these calls and should convert storage markup to plain text while retaining `id`, `title`, `url`, `version.number`, and `version.createdAt` for citations and freshness.

Documentation: [Confluence page API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/), [space API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-space/), [API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/).

## Dummy Confluence → Qwen workflow

The local server already serves `/raid/models/Qwen3.5-27B` as `qwen-spec-poc` at `http://127.0.0.1:8500/v1`. Run:

```bash
python3 confluence/dummy_workflow.py --question 'What is the current payment-service recovery procedure?'
```

`dummy_workflow.py` resolves the runbook's page ID from `page_manifest.json`, invokes `confluence_cli.py read` to fetch the **current** page text, and sends that text and the question to the running vLLM chat-completions endpoint. The answer includes the Confluence page URL. Use `--slug postmortem` for another page or `--fetch-only` to inspect retrieval without a model call. `VLLM_BASE_URL` and `VLLM_MODEL` can override the defaults.

This is a single-page workflow. It does not yet choose relevant pages, combine platforms, or enforce per-user Confluence permissions. Add a user-specific permission gate before any retrieved text is sent to the model when the site is upgraded for the access-control demo.

# Google Drive hackathon fixture

One fictional Google Doc, *INC-PAY-001 payment metrics report*, in a folder named `INC-PAY-001`. It holds the final reconciled impact numbers that the Confluence pages call provisional. Access is granted per user on the folder, so the Doc inherits it.

## One-time setup

Use an established Google account, and keep company names out of the project name. A brand-new account with a company name in the project was flagged for a terms-of-service review once, which disabled the service account until the appeal went through.

1. **Google Cloud project.** At <https://console.cloud.google.com>, create a project (e.g. `corporate-chat-demo`) and enable the **Google Drive API** under *APIs & Services → Library*.
2. **Service account.** Under *IAM & Admin → Service accounts*, create `corporate-chat-drive`. No project roles are needed. Open it, go to *Keys → Add key → JSON*, and save the file as `gdrive/service_account.json`. It is ignored by Git. Keep it out of chat.
3. **Folder and Doc.** In Google Drive, signed in as the account that will own the data:
   - Create a folder named `INC-PAY-001`.
   - Inside it, create a blank Google Doc named exactly `INC-PAY-001 payment metrics report`.
   - Share the folder with the service account's `client_email` (from the JSON key) as **Editor**. Drive only lists a file's permissions to callers who can share it, and the `seed`, `share`, and `unshare` commands need edit access.
   - Copy the folder ID from its URL: `https://drive.google.com/drive/folders/<FOLDER_ID>`.
4. **`.env`** in the repository root:

   ```text
   GOOGLE_SERVICE_ACCOUNT_FILE=gdrive/service_account.json
   GDRIVE_FOLDER_ID=<FOLDER_ID>
   ```

5. **Users.** Put each user's Google account in `google_email` in `main_workflow/identities.json` (not in Git; see `identities.example.json`). Each user needs a separate real Google account; Gmail plus addresses map to the same account. The folder owner always has access, so give ownership to the user who should see everything (Zhao, the CTO), never to the contractor (Terrance).

## Seed and check

```bash
python3 gdrive/gdrive_cli.py check
python3 gdrive/gdrive_cli.py seed            # writes seed_report.html into the blank Doc
python3 gdrive/gdrive_cli.py share ShiHan     # reader on the folder, no notification email
python3 gdrive/gdrive_cli.py access          # who can see the folder and each file
python3 gdrive/gdrive_cli.py list            # writes file_manifest.json
python3 gdrive/gdrive_cli.py read FILE_ID
```

Do not share with Terrance; the contractor must not see the report.

The service account cannot own files (it has no storage quota), which is why the Doc is created by hand and the script only fills it in.

## Revocation demo

```bash
python3 gdrive/gdrive_cli.py unshare ShiHan
```

The next question from ShiHan must no longer cite the report. `main_workflow` checks Drive permissions live on every question, so no resync is needed.

## API handoff

`main_workflow/sources/gdrive.py` uses the same client with the read-only scope.

| Method | Drive API v3 call |
|---|---|
| `search` | `files.list` with `fullText contains '...'` |
| `can_access` | `permissions.list` on the file; allows a matching user email, a matching domain, or `anyone` |
| `fetch` | `files.get`, then `files.export` as `text/plain` for Google Docs |
| `changes_since` | `files.list` with `modifiedTime > '...'` |

Group shares are not resolved, since that needs the Admin SDK. Share with individual users.

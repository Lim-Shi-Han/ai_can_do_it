# Company A's Google Drive

Zhao (the CTO) owns the folder tree. Each person owns the files they wrote, and only one folder is ever shared outside the company: the one the payment processor uses during INC-PAY-001.

| Folder | ShiHan | Zhao | Ivan | Sheldon | Terrance |
|---|---|---|---|---|---|
| `Company A/Payments Engineering` | edit | owner | edit | · | · |
| `Company A/Finance` | one file (comment) | owner | · | edit | · |
| `Company A/Security` | · | owner | edit | · | · |
| `Company A/Vendors/PayProcessor` | view | owner | comment | edit | · |
| `…/PayProcessor/INC-PAY-001 shared with PayProcessor` | view | owner | comment | edit | edit, steps 3 to 8 only |

Elson has no Drive access. The single shared file is *Scheme fee schedule 2026* in Finance, shared with ShiHan as commenter; it shows file-level sharing next to folder-level sharing.

`demo_drive.json` lists the folders, who gets which role, 15 standing files with their owners, and the 3 files created during the demo. Standing files never use the demo questions' words, so the chat does not retrieve them.

## One-time setup

Use an established Google account, and keep company names out of the project name. A brand-new account with a company name in the project was flagged for a terms-of-service review once, which disabled the service account until the appeal went through.

1. **Google Cloud project.** At <https://console.cloud.google.com>, create a project and enable the **Google Drive API** under *APIs & Services → Library*.
2. **Service account.** Under *IAM & Admin → Service accounts*, create one with no project roles. Under *Keys → Add key → JSON*, save the key as `gdrive/service_account.json` (ignored by Git; keep it out of chat).
3. **`.env`** in the repository root:

   ```text
   GOOGLE_SERVICE_ACCOUNT_FILE=gdrive/service_account.json
   GDRIVE_FOLDER_ID=<the folder shared with the processor>
   ```

4. **Users.** Put each person's Google account in `google_email` in `main_workflow/identities.json` (not in Git; see `identities.example.json`). Drive can only share with an address that has a Google account.

## Build, upload, set up

The service account can share folders but cannot create files (it has no storage), so each person uploads their own files.

```bash
python3 gdrive/demo_drive.py build --date 2026-10-15   # writes gdrive/upload/: one folder per person, plus HOW TO UPLOAD.txt
```

1. **Zhao** drags `gdrive/upload/1 Zhao - …/Company A` into My Drive, which creates the folder tree with his files, then shares `Company A` with the service account's email as Editor.
2. Run `python3 gdrive/demo_drive.py setup`. It:
   - shares every folder as in the table
   - moves the existing `INC-PAY-001` folder (`GDRIVE_FOLDER_ID`) into `Vendors/PayProcessor` and renames it
   - moves the old *INC-PAY-001 payment metrics report* to the trash, or says that Zhao must delete it. It holds the final figures that step 7 works out, so it must be gone before Terrance is shared.
3. **ShiHan, Ivan, Sheldon** open *Shared with me → Company A*, then the folder named in their `2 <name>/into …` folder, and drag the files in (not the folder).
4. Run `setup` again (for the single shared file), then `check`:

```bash
python3 gdrive/demo_drive.py check    # every file present, owned by the right person, readable; flags extras
python3 gdrive/demo_drive.py access   # who can open each file, from Drive's permissions
```

Uploads stay Word and CSV files; leave *Convert uploads* off in Drive's settings. The app reads Word, CSV, Google Docs, and Google Sheets.

## The demo files

Built for the rehearsal date into `gdrive/upload/3 demo <date>/` and uploaded live into the processor folder:

| Step | Uploaded by | File | Holds |
|---|---|---|---|
| 3 | Terrance | `PP-58213 issuer timeouts <date> 1400-1425.csv` | Requests and timeouts per minute from 14:00, exported mid-incident: 387 timeouts since 14:10 and rising |
| 7 | Terrance | `PP-58213 settlement export <date> 1410-1502.csv` | 13,640 requests, 1,312 failed with no answer, none settled; the processor cannot tell which later payments were retries |
| 7 | Sheldon | `Company A payment records for PP-58213 (copy for PayProcessor).csv` | All 1,312 matched; 1,098 failed cleanly, 214 succeeded on retry, 0 charged twice; 87 late approvals released |

The processor's files use its own case number (PP-58213), never `INC-PAY-001` or the words "incident", "report", "security", or "breach", so in step 9 Terrance's own files do not answer his question about the incident report. The timeout log names the `payment-service` endpoint, so ShiHan's step 4 question finds it.

## Sharing and revocation

```bash
python3 gdrive/gdrive_cli.py share Terrance --role editor   # step 3
python3 gdrive/gdrive_cli.py unshare Terrance               # step 8
```

`share` takes `--role viewer|commenter|editor` and changes the role if the person already has a different one. `main_workflow` checks Drive permissions live on every question, so no resync is needed after a change.

After step 8 Terrance loses the payment records copy (Sheldon's file) and with it the 214-retry figure. He keeps the two files he uploaded: in personal Google accounts the uploader owns the file.

## Before each rehearsal

```bash
python3 gdrive/demo_drive.py reset --yes
```

It removes Terrance from the processor folder and empties it. Only a file's owner can delete it, so `reset` lists the uploads that Terrance or Sheldon must delete in Drive.

## Acting as a person (optional)

With a sign-in client, commands can run as a person instead of the service account (`--as NAME`), for example so Drive records Zhao as the one who shared. This needs one Desktop app client and one sign-in per person:

1. In a Google Cloud project with the Drive API enabled, open *Google Auth Platform*: audience **External**, add each person's Google address under *Audience → Test users*, and add the scope `https://www.googleapis.com/auth/drive` under *Data access*.
2. *Clients → Create client → Desktop app*, download the JSON, and save it as `gdrive/oauth_client.json` (ignored by Git).
3. Each person signs in once; the token goes to `gdrive/tokens/<Name>.json` (ignored by Git):

```bash
python3 gdrive/gdrive_cli.py login Zhao               # opens the browser; choose Continue on the "not verified" warning
python3 gdrive/gdrive_cli.py login Terrance --paste   # for someone on another computer
python3 gdrive/gdrive_cli.py share Terrance --role editor --as Zhao
```

`login` refuses to save if the person signs in with a Google account other than their `google_email`. In testing mode, sign-ins expire after 7 days.

## Other commands

```bash
python3 gdrive/gdrive_cli.py check            # the service account can see GDRIVE_FOLDER_ID
python3 gdrive/gdrive_cli.py access           # who can see that folder and each file in it
python3 gdrive/gdrive_cli.py list             # writes file_manifest.json
python3 gdrive/gdrive_cli.py read FILE_ID
```

`seed` and `seed_report.html` belong to the earlier story (the old metrics report) and are no longer used.

## API handoff

`main_workflow/sources/gdrive.py` uses the same client with the read-only scope.

| Method | Drive API v3 call |
|---|---|
| `search` | `files.list` with `fullText contains '...'` |
| `can_access` | `permissions.list` on the file; allows a matching user email, a matching domain, or `anyone` |
| `fetch` | `files.get`, then the text: Google Docs exported as Markdown, Google Sheets as CSV, Word files read from the download, CSV and text files as they are |
| `changes_since` | `files.list` with `modifiedTime > '...'` |

Group shares are not resolved, since that needs the Admin SDK. Share with individual users.

# Company A's Google Drive

New to this? Start with [SETUP.md](SETUP.md): the files to get, the `.env` lines, and how to check that everything works.

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

## Who does what

| Account | Does |
|---|---|
| Service account (`service_account.json`) | Reads files for the app, checks who can open each one, shares and unshares folders |
| Each person's own sign-in (`gdrive/tokens/<Name>.json`) | Creates files, so the person is the owner. The service account cannot: it has no storage, and with personal Google accounts it cannot act as anyone |

## Sign-ins (one-time)

1. In a Google Cloud project with the Drive API enabled, open *Google Auth Platform*: audience **External**, add the Google addresses of Zhao, ShiHan, Ivan, Sheldon, and Terrance under *Audience → Test users*, and add the scope `https://www.googleapis.com/auth/drive` under *Data access*.
2. *Clients → Create client → Desktop app*, download the JSON, and save it as `gdrive/oauth_client.json` (ignored by Git). One client serves everyone.
3. Each person signs in once. The browser opens; they sign in, choose **Continue** on "Google hasn't verified this app", and allow Drive access. The token goes to `gdrive/tokens/<Name>.json` (ignored by Git):

```bash
python3 gdrive/gdrive_cli.py login Zhao
python3 gdrive/gdrive_cli.py login Terrance --paste   # for someone on another computer: they open the link and send back the final address
python3 gdrive/gdrive_cli.py check --as Zhao          # whose sign-in it is
```

`login` refuses to save if the person signs in with a Google account other than their `google_email`. A token gives full access to that person's Drive, so keep `gdrive/tokens/` private; anyone can revoke it at <https://myaccount.google.com/permissions>. While the app is in testing mode, sign-ins expire after 7 days: sign in again before a demo.

## Seed and check

```bash
python3 gdrive/demo_drive.py seed     # creates whatever is missing; safe to rerun
python3 gdrive/demo_drive.py check    # every file present, owned by the right person, readable; flags extras
python3 gdrive/demo_drive.py access   # who can open each file, from Drive's permissions
```

`seed`:
1. As Zhao: creates `Company A` and the folders in it, including the empty processor folder, and shares `Company A` with the service account as editor.
2. As the service account: shares each folder as in the table above.
3. As each owner: uploads their files. Anyone not signed in yet is skipped and listed; run `seed` again after they sign in.
4. As the service account: shares *Scheme fee schedule 2026* with ShiHan.

When it prints a new `GDRIVE_FOLDER_ID`, put that in `.env`. Files are Word and CSV; the app reads Word, CSV, Google Docs, and Google Sheets.

`seed` also removes people's direct access to `Company A` (a share there would reach every folder) and leaves files someone else uploaded alone; `seed --fix-owners` has the right owner upload their own copy and moves the other copy to its owner's trash. `check` also compares every folder's sharing with the table above.

**Sheldon** uploads his own files, including the step 7 payment records, with his sign-in (`britanniagbr@gmail.com`). If a persona loses their sign-in, `uploaded_by` in `demo_drive.json` can name someone to upload for them; see `SETUP.md`.

**Without sign-ins**, people upload by hand instead: `build` writes the files into `gdrive/upload/` with `HOW TO UPLOAD.txt`; Zhao uploads the `Company A` folder and shares it with the service account; `setup` shares the folders; the others drag their files in; `setup` and `check` again.

## The demo files

Uploaded live into the processor folder, dated with the day of the demo (or `--date`):

```bash
python3 gdrive/demo_drive.py upload 3            # Terrance's timeout log
python3 gdrive/demo_drive.py upload 7 Terrance   # the settlement export
python3 gdrive/demo_drive.py upload 7 Sheldon    # Company A's payment records copy
```

Drive itself checks access: Terrance's upload is refused until the folder is shared with him as editor. People can also upload the same files by hand from `gdrive/upload/3 demo <date>/` (`build`).

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

`share` takes `--role viewer|commenter|editor` and changes the role if the person already has a different one; add `--as Zhao` to share with Zhao's sign-in, so Drive's activity log names him. The console's Drive button still shares as viewer only, which is not enough for Terrance to upload; use the command above for step 3 until the console passes the role. `main_workflow` checks Drive permissions live on every question, so no resync is needed after a change.

After step 8 Terrance loses the payment records copy (Sheldon's file) and with it the 214-retry figure. He keeps the two files he uploaded: in personal Google accounts the uploader owns the file.

## Before each rehearsal

```bash
python3 gdrive/demo_drive.py reset --yes
```

It removes Terrance from the processor folder and moves the demo uploads to their owners' trash, using each owner's sign-in (only the owner can delete a file). Uploads by someone who has not signed in are listed for them to delete in Drive.

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

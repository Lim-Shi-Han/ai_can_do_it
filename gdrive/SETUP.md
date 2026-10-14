# Google Drive: setup for teammates

What you need before you can run anything that touches Company A's Google Drive: the chat's Drive source, `gdrive/gdrive_cli.py`, and `gdrive/demo_drive.py`. It takes about 10 minutes. You do not need a Google Cloud account or any persona's password.

## How it fits together

| Piece | What it is | Used for |
|---|---|---|
| `gdrive/service_account.json` | The app's own Google account (a "service account", the robot) | Reading files, checking who can open each one, sharing and unsharing folders. The chat uses only this |
| `gdrive/oauth_client.json` | Identifies our sign-in app to Google | Needed to use the persona sign-ins below |
| `gdrive/tokens/<Name>.json` | A saved Google sign-in for one persona | Uploading files as that person, so Drive shows them as the owner |

The robot cannot create files (Google gives it no storage) and cannot act as a person (personal Google accounts do not allow that), so uploads use the persona sign-ins. This is the Drive version of the per-person Jira tokens (`JIRA_TOKEN_SHIHAN` and so on).

## 1. Files you get from Shi Han

Ask Shi Han for these. They must be sent privately (a direct message or a password manager), never through Git, a group chat, or a screenshot. All of these locations are ignored by Git.

| File | Put it at | Notes |
|---|---|---|
| Robot key | `gdrive/service_account.json` | |
| Sign-in client | `gdrive/oauth_client.json` | |
| Persona sign-ins | `gdrive/tokens/Zhao.json`, `ShiHan.json`, `Ivan.json`, `Terrance.json` | Each one gives full access to that persona's Google Drive. Sheldon has none yet (see below) |
| Identities | `main_workflow/identities.json` | Holds the real email addresses, including each persona's `google_email` |

Then add these two lines to `.env` in the repository root (see `.env.example`):

```text
GOOGLE_SERVICE_ACCOUNT_FILE=gdrive/service_account.json
GDRIVE_FOLDER_ID=1JJtvYZR1cd2VRUCNsptC4Hvqj9fHfo-L
```

The folder ID is not a secret. It is the folder shared with the payment processor, `Company A/Vendors/PayProcessor/INC-PAY-001 shared with PayProcessor`.

## 2. Install

The repository's packages (including `cryptography`, which Drive needs) are listed in `pyproject.toml`. Install them once with [uv](https://docs.astral.sh/uv/):

```bash
uv sync                          # creates .venv from pyproject.toml and uv.lock
.venv\Scripts\activate           # Windows; on macOS or Linux: source .venv/bin/activate
```

With the environment active, every `python ...` command in these docs uses it. Without activating, prefix commands with `uv run`, for example `uv run python -m main_workflow.web`. To add a package, run `uv add <package>`; it updates `pyproject.toml` and `uv.lock`, which are both committed.

## 3. Check that it works

```bash
python gdrive/gdrive_cli.py check                  # the robot: "... folder 'INC-PAY-001 shared with PayProcessor' ... is visible"
python gdrive/gdrive_cli.py check --as Zhao        # repeat for ShiHan, Ivan, Terrance: "Signed in as <their Google address>"
python gdrive/demo_drive.py check                  # ends with "All files are in place."
python gdrive/demo_drive.py access                 # who can open each folder and file
python -m main_workflow.sync --once --full         # rebuild the chat's search index from what is in Drive now
```

Before step 3 of the demo, `check --as Terrance` says the folder is not shared with him. That is correct.

## 4. During the demo

```bash
python gdrive/gdrive_cli.py share Terrance --role editor   # step 3: Zhao gives the processor access
python gdrive/demo_drive.py upload 3                       # step 3: Terrance uploads the timeout log
python gdrive/demo_drive.py upload 7 Terrance              # step 7: the processor's settlement export
python gdrive/demo_drive.py upload 7 Sheldon               # step 7: Company A's payment records (uploaded by Zhao for now)
python gdrive/gdrive_cli.py unshare Terrance               # step 8: access removed
```

Press **Sync now** in the console after each upload, before anyone asks. If Terrance's upload runs before the share, Drive refuses it; that is a real permission check, and you can show it on purpose.

## 5. Before each rehearsal

```bash
python gdrive/demo_drive.py reset --yes   # removes Terrance and deletes the demo uploads, as their owners
python gdrive/demo_drive.py check
python -m main_workflow.sync --once --full
```

## Sign-ins expire after 7 days

Our sign-in app is in Google's testing mode, so each persona sign-in stops working 7 days after it was made. You will see:

```text
Error: Zhao's Google sign-in has expired or was revoked; run: python gdrive/gdrive_cli.py login Zhao
```

Renewing needs that persona's Google account, so ask Shi Han to run `login` again and send you the new token file. The day before a demo, run `check --as` for Zhao, ShiHan, Ivan, and Terrance.

To renew on your own machine, you need the persona's Google password, and the account must be a test user (it already is). Run `python gdrive/gdrive_cli.py login Zhao`, pick that account in the browser, choose **Continue** on "Google hasn't verified this app", then **Allow**. `login` refuses to save a sign-in for the wrong Google account.

## Sheldon

Sheldon's Google account cannot sign in yet, so `uploaded_by` in `gdrive/demo_drive.json` has Zhao upload his files. Drive shows Zhao as their owner; Sheldon still has his own access, so the chat's checks for him are unaffected. When Sheldon has a working account:

1. Put its address in `google_email` for Sheldon in `main_workflow/identities.json`, and add it as a test user (below).
2. `python gdrive/gdrive_cli.py login Sheldon`
3. Remove the `Sheldon` entry from `uploaded_by` in `gdrive/demo_drive.json`.
4. `python gdrive/demo_drive.py seed --fix-owners`: Sheldon uploads his own copies, and Zhao's copies go to Zhao's trash.
5. `python gdrive/demo_drive.py check`: it also lists the old account if it can still open a folder.

## The Google Cloud side

For whoever manages it, in project `tencent-hackathon-511003`:

| Where | What is there |
|---|---|
| *Google Auth Platform → Audience → Test users* | The persona Google addresses. Anyone else trying to sign in gets "Access blocked" |
| *Google Auth Platform → Clients* | The Desktop app client that `oauth_client.json` comes from |
| *IAM & Admin → Service accounts* | `internal-file-drive`, whose key is `service_account.json` |

## Troubleshooting

| Message | Fix |
|---|---|
| `Set GOOGLE_SERVICE_ACCOUNT_FILE ...` | The `.env` lines from step 1 are missing |
| `No Google sign-in saved for X` | `gdrive/tokens/X.json` is missing; get it from Shi Han |
| `X's Google sign-in has expired or was revoked` | Renew it (see above) |
| `Drive refused: Terrance cannot add files ...` | Share the folder with Terrance as editor first (step 3) |
| `No folder 'Company A' owned by Zhao is shared with ...` | Wrong `service_account.json`, or the folder's sharing changed; ask Shi Han |
| `Access blocked` or `access_denied` during `login` | That Google address is not a test user |
| `Signed in as ..., but identities.json has ...` | The wrong Google account was picked during `login`; nothing was saved |
| `check` lists `WRONG`, `MISSING`, or a sharing problem | Run `python gdrive/demo_drive.py seed` (add `--fix-owners` for a wrong owner), then `check` again |

## If a key or token leaks

- **Persona token:** that persona removes our app under *Third-party apps with account access* at <https://myaccount.google.com/permissions>, then signs in again with `login`.
- **Robot key:** delete the key in *IAM & Admin → Service accounts → internal-file-drive → Keys* and create a new one.

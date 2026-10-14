#!/usr/bin/env python3
"""Seed and inspect the hackathon Google Drive folder using Drive API v3, as the service account or as a person."""

import argparse
import base64
import hashlib
import http.server
import io
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed_report.html"
MANIFEST = ROOT / "file_manifest.json"
OAUTH_CLIENT = ROOT / "oauth_client.json"
TOKENS = ROOT / "tokens"
IDENTITIES = Path(os.environ.get("IDENTITIES_FILE") or ROOT.parent / "main_workflow" / "identities.json")
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
REPORT_TITLE = "INC-PAY-001 payment metrics report"
SEED_MARKER = "Fictional hackathon data"
FULL_SCOPE = "https://www.googleapis.com/auth/drive"
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
ROLES = {"viewer": "reader", "commenter": "commenter", "editor": "writer"}
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_EXTENSIONS = (".csv", ".txt", ".md", ".log")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FOLDER = "application/vnd.google-apps.folder"


def load_local_env():
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in {"GOOGLE_SERVICE_ACCOUNT_FILE", "GDRIVE_FOLDER_ID"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def docx_text(data):
    """Text of a Word file: headings as '## ', table rows as 'a | b | c', in document order."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = ElementTree.fromstring(z.read("word/document.xml")).find(f"{W}body")

    def para(p):
        style = p.find(f"{W}pPr/{W}pStyle")
        text = re.sub(r"^[•●▪]\s*", "- ", "".join(t.text or "" for t in p.iter(f"{W}t")))
        level = style.get(f"{W}val", "") if style is not None else ""
        return ("# " if level == "Title" else "## " if level.startswith("Heading") else "") + text if text else ""

    lines = []
    for block in body:
        if block.tag == f"{W}p":
            lines.append(para(block))
        elif block.tag == f"{W}tbl":
            for row in block.iter(f"{W}tr"):
                lines.append(" | ".join(" ".join(filter(None, (para(p) for p in cell.iter(f"{W}p"))))
                                        for cell in row.iter(f"{W}tc")))
    return "\n".join(line for line in lines if line.strip())


def post_form(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Google token endpoint returned HTTP {exc.code}: {detail}") from exc


def oauth_client():
    """The Desktop app client from Google Auth Platform → Clients; one file serves every person."""
    if not OAUTH_CLIENT.exists():
        raise ValueError(f"Download the Desktop app client from Google Auth Platform > Clients and save it as gdrive/{OAUTH_CLIENT.name}")
    data = json.loads(OAUTH_CLIENT.read_text(encoding="utf-8"))
    if "installed" not in data:
        raise ValueError(f"gdrive/{OAUTH_CLIENT.name} is not a Desktop app client (it has no 'installed' section)")
    return data["installed"]


def token_path(name):
    return TOKENS / f"{name}.json"


class GoogleDrive:
    def __init__(self, scope=FULL_SCOPE, user=None):
        """The service account by default; with user, that person's saved sign-in from `login`."""
        self.user, self.scope, self.key, self.login = user, scope, None, None
        if user:
            if not token_path(user).exists():
                raise ValueError(f"No Google sign-in saved for {user}; run: python gdrive/gdrive_cli.py login {user}")
            self.login = json.loads(token_path(user).read_text(encoding="utf-8"))
        else:
            key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
            if not key_file:
                raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_FILE to the service account JSON key")
            path = Path(key_file).expanduser()
            if not path.is_absolute():
                path = ROOT.parent / path
            self.key = json.loads(path.read_text(encoding="utf-8"))
        folder = os.environ.get("GDRIVE_FOLDER_ID", "")
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", folder)
        self.folder_id = match.group(1) if match else folder or None
        self._token, self._token_exp = None, 0

    @property
    def email(self):
        return self.login["email"] if self.user else self.key["client_email"]

    def token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        now = int(time.time())
        if self.user:
            client = oauth_client()
            try:
                result = post_form(client["token_uri"], {
                    "grant_type": "refresh_token", "refresh_token": self.login["refresh_token"],
                    "client_id": client["client_id"], "client_secret": client["client_secret"],
                })
            except RuntimeError as exc:
                if "invalid_grant" in str(exc):
                    # test-mode sign-ins last 7 days
                    raise RuntimeError(f"{self.user}'s Google sign-in has expired or was revoked; "
                                       f"run: python gdrive/gdrive_cli.py login {self.user}") from exc
                raise
        else:
            header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
            claims = b64url(json.dumps({
                "iss": self.key["client_email"], "scope": self.scope,
                "aud": self.key["token_uri"], "iat": now, "exp": now + 3600,
            }).encode())
            private_key = serialization.load_pem_private_key(self.key["private_key"].encode(), password=None)
            signature = private_key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
            result = post_form(self.key["token_uri"], {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": f"{header}.{claims}.{b64url(signature)}",
            })
        self._token, self._token_exp = result["access_token"], now + result.get("expires_in", 3600)
        return self._token

    def request(self, method, url, params=None, payload=None, data=None, content_type=None, raw=False):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Bearer {self.token()}"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"Drive API returned HTTP {exc.code}: {detail}") from exc
        if raw == "bytes":
            return body
        if raw:
            return body.decode("utf-8", errors="replace")
        return json.loads(body) if body else {}

    def list_files(self, q, fields="id,name,mimeType,version,modifiedTime,webViewLink,parents"):
        params = {"q": q, "fields": f"nextPageToken,files({fields})", "pageSize": 100}
        files = []
        while True:
            response = self.request("GET", f"{API}/files", params)
            files.extend(response.get("files", []))
            if not response.get("nextPageToken"):
                return files
            params["pageToken"] = response["nextPageToken"]

    def file(self, file_id):
        return self.request("GET", f"{API}/files/{file_id}", {
            "fields": "id,name,mimeType,version,modifiedTime,webViewLink,parents,trashed",
        })

    def text(self, meta):
        if meta["mimeType"] == GOOGLE_DOC:
            # markdown keeps tables readable; plain text flattens them to one cell per line
            try:
                text = self.request("GET", f"{API}/files/{meta['id']}/export", {"mimeType": "text/markdown"}, raw=True)
            except RuntimeError:
                text = self.request("GET", f"{API}/files/{meta['id']}/export", {"mimeType": "text/plain"}, raw=True)
            return text.lstrip("﻿").replace("\r\n", "\n")
        if meta["mimeType"] == GOOGLE_SHEET:
            # the first sheet only; Drive exports one sheet per CSV
            text = self.request("GET", f"{API}/files/{meta['id']}/export", {"mimeType": "text/csv"}, raw=True)
            return text.lstrip("﻿").replace("\r\n", "\n")
        name = meta["name"].lower()
        if meta["mimeType"] == DOCX or name.endswith(".docx"):
            return docx_text(self.request("GET", f"{API}/files/{meta['id']}", {"alt": "media"}, raw="bytes"))
        # browsers on Windows often label .csv as application/vnd.ms-excel, so trust the extension too
        if meta["mimeType"].startswith("text/") or name.endswith(TEXT_EXTENSIONS):
            text = self.request("GET", f"{API}/files/{meta['id']}", {"alt": "media"}, raw=True)
            return text.lstrip("﻿").replace("\r\n", "\n")
        return ""

    def permissions(self, file_id):
        params = {"fields": "nextPageToken,permissions(id,type,role,emailAddress,domain,deleted)", "pageSize": 100}
        perms = []
        while True:
            response = self.request("GET", f"{API}/files/{file_id}/permissions", params)
            perms.extend(response.get("permissions", []))
            if not response.get("nextPageToken"):
                return perms
            params["pageToken"] = response["nextPageToken"]

    def folder(self):
        if not self.folder_id:
            raise ValueError("Set GDRIVE_FOLDER_ID to the ID of the INC-PAY-001 folder")
        meta = self.file(self.folder_id)
        if meta["mimeType"] != FOLDER:
            raise RuntimeError(f"{self.folder_id} is not a folder")
        return meta

    def folder_files(self):
        return self.list_files(f"'{self.folder_id}' in parents and trashed = false")


def persona_email(name):
    users = {u["name"]: u for u in json.loads(IDENTITIES.read_text(encoding="utf-8"))["users"]}
    if name not in users:
        raise ValueError(f"No user {name!r} in {IDENTITIES}")
    email = users[name].get("google_email")
    if not email:
        raise ValueError(f"{name} has no google_email in {IDENTITIES}")
    return email.lower()


def user_permission(drive, item, email):
    return next((p for p in drive.permissions(item["id"])
                 if p["type"] == "user" and (p.get("emailAddress") or "").lower() == email), None)


def share(drive, item, name, role="viewer"):
    """Give name the role (viewer, commenter, editor) on a file or folder, without a notification email."""
    email, labels = persona_email(name), {v: k for k, v in ROLES.items()}
    actor = drive.user or "The service account"
    existing = user_permission(drive, item, email)
    if existing and existing["role"] in (ROLES[role], "owner"):
        return f"{name} already has {labels.get(existing['role'], existing['role'])} access to {item['name']}"
    if existing:
        drive.request("PATCH", f"{API}/files/{item['id']}/permissions/{existing['id']}", payload={"role": ROLES[role]})
        return (f"{actor} changed {name}'s access to {item['name']} from "
                f"{labels.get(existing['role'], existing['role'])} to {role}")
    drive.request(
        "POST", f"{API}/files/{item['id']}/permissions", {"sendNotificationEmail": "false"},
        payload={"type": "user", "role": ROLES[role], "emailAddress": email},
    )
    return f"{actor} shared {item['name']} with {name} ({email}) as {role}"


def unshare(drive, item, name):
    email = persona_email(name)
    existing = user_permission(drive, item, email)
    if not existing:
        return f"{name} ({email}) has no direct access to {item['name']}"
    if existing["role"] == "owner":
        raise RuntimeError(f"{name} owns {item['name']}; ownership cannot be revoked here")
    drive.request("DELETE", f"{API}/files/{item['id']}/permissions/{existing['id']}", raw=True)
    return f"{drive.user or 'The service account'} removed {name} ({email}) from {item['name']}"


def login(name, paste=False):
    """One-time Google sign-in for a person (OAuth with PKCE on a loopback address); saves their refresh token."""
    client, email = oauth_client(), persona_email(name)
    verifier, state = b64url(secrets.token_bytes(48)), secrets.token_urlsafe(16)
    received = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state") == [state]:
                received.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab." if "code" in received else b"Sign-in did not finish; check the terminal.")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Callback)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = client["auth_uri"] + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": FULL_SCOPE, "access_type": "offline", "prompt": "consent", "login_hint": email,
        "state": state, "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    })
    print(f"Sign in as {name} ({email}). If Google says the app isn't verified, choose Continue.")
    if paste:
        # for someone on another computer: the final page fails to load there, but its address holds the code
        server.server_close()
        print(f"\nOpen this link, sign in, then copy the address of the page it ends on (starts with {redirect}):\n\n{url}\n")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(input("Paste that address here: ").strip()).query)
        if query.get("state") == [state]:
            received.update({k: v[0] for k, v in query.items()})
    else:
        print(f"Opening the browser. If it doesn't open, visit:\n{url}")
        webbrowser.open(url)
        server.timeout, deadline = 5, time.time() + 300
        while "code" not in received and "error" not in received and time.time() < deadline:
            server.handle_request()
        server.server_close()
    if "code" not in received:
        raise RuntimeError(f"Google sign-in did not finish: {received.get('error', 'no response within 5 minutes')}")

    result = post_form(client["token_uri"], {
        "code": received["code"], "client_id": client["client_id"], "client_secret": client["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if "refresh_token" not in result:
        raise RuntimeError("Google returned no refresh token; sign in again")
    req = urllib.request.Request(f"{API}/about?fields=user(emailAddress)",
                                 headers={"Authorization": f"Bearer {result['access_token']}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            signed_in = json.load(response)["user"]["emailAddress"].lower()
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Drive API returned HTTP {exc.code}: {detail}") from exc
    if signed_in != email:
        raise RuntimeError(f"Signed in as {signed_in}, but identities.json has {email} for {name}; nothing saved")
    TOKENS.mkdir(exist_ok=True)
    token_path(name).write_text(json.dumps({
        "name": name, "email": signed_in, "refresh_token": result["refresh_token"],
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2) + "\n", encoding="utf-8")
    return token_path(name)


def save_manifest(drive, folder, files):
    data = {
        "source": "gdrive",
        "folder_id": folder["id"],
        "folder_name": folder["name"],
        "files": [
            {k: f.get(k) for k in ("id", "name", "mimeType", "version", "modifiedTime", "webViewLink")}
            for f in files
        ],
    }
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["login", "check", "seed", "list", "read", "access", "share", "unshare"])
    parser.add_argument("target", nargs="*", help="file ID for read, user names for login/share/unshare")
    parser.add_argument("--as", dest="as_user", metavar="NAME", help="use NAME's saved Google sign-in instead of the service account")
    parser.add_argument("--paste", action="store_true", help="login: print the link and paste back the final address (signing in on another computer)")
    parser.add_argument("--role", choices=list(ROLES), default="viewer", help="share: access level on the folder")
    args = parser.parse_args()

    if args.command == "login":
        if len(args.target) != 1:
            parser.error("login requires one user name from identities.json")
        path = login(args.target[0], paste=args.paste)
        print(f"Saved {args.target[0]}'s Google sign-in to gdrive/tokens/{path.name}")
        return

    drive = GoogleDrive(user=args.as_user)
    if args.command == "check":
        try:
            folder = drive.folder()
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            print(f"Signed in as {drive.email}; folder {drive.folder_id} is not shared with this account")
            return
        print(f"Signed in as {drive.email}; folder {folder['name']!r} ({folder['id']}) is visible")
        return
    folder = drive.folder()

    if args.command == "seed":
        matches = [f for f in drive.folder_files() if f["name"] == REPORT_TITLE]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one Google Doc named {REPORT_TITLE!r} in the folder, found {len(matches)}. "
                "Create a blank Doc with that name in Drive first."
            )
        doc = matches[0]
        if SEED_MARKER in drive.text(doc):
            print("Report already seeded")
        else:
            drive.request(
                "PATCH", f"{UPLOAD_API}/files/{doc['id']}", {"uploadType": "media"},
                data=SEED.read_bytes(), content_type="text/html",
            )
            print(f"Seeded {REPORT_TITLE}")

    if args.command == "read":
        if len(args.target) != 1:
            parser.error("read requires one file ID")
        meta = drive.file(args.target[0])
        print(json.dumps({
            "id": meta["id"], "title": meta["name"], "url": meta.get("webViewLink"),
            "version": meta.get("version"), "updated_at": meta.get("modifiedTime"),
            "text": drive.text(meta).strip(),
        }, indent=2, ensure_ascii=False))
        return

    if args.command == "access":
        for f in [folder] + drive.folder_files():
            print(f"{f['name']}:")
            for p in drive.permissions(f["id"]):
                print(f"  {p['role']:<10} {p['type']:<7} {p.get('emailAddress') or p.get('domain') or ''}")
        return

    if args.command in {"share", "unshare"}:
        if not args.target:
            parser.error(f"{args.command} requires at least one user name from identities.json")
        for name in args.target:
            print(share(drive, folder, name, args.role) if args.command == "share" else unshare(drive, folder, name))
        return

    manifest = save_manifest(drive, folder, drive.folder_files())
    for f in manifest["files"]:
        print(f"{f['id']} v{f['version']} {f['name']} — {f['webViewLink']}")
    print(f"Manifest saved to {MANIFEST}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

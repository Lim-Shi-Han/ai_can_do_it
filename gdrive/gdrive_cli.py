#!/usr/bin/env python3
"""Seed and inspect the hackathon Google Drive folder using Drive API v3 and a service account."""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed_report.html"
MANIFEST = ROOT / "file_manifest.json"
IDENTITIES = ROOT.parent / "main_workflow" / "identities.json"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
REPORT_TITLE = "INC-PAY-001 payment metrics report"
SEED_MARKER = "Fictional hackathon data"
FULL_SCOPE = "https://www.googleapis.com/auth/drive"
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC = "application/vnd.google-apps.document"
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


class GoogleDrive:
    def __init__(self, scope=FULL_SCOPE):
        key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not key_file:
            raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_FILE to the service account JSON key")
        path = Path(key_file).expanduser()
        if not path.is_absolute():
            path = ROOT.parent / path
        self.key = json.loads(path.read_text(encoding="utf-8"))
        self.scope = scope
        folder = os.environ.get("GDRIVE_FOLDER_ID", "")
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", folder)
        self.folder_id = match.group(1) if match else folder or None
        self._token, self._token_exp = None, 0

    @property
    def email(self):
        return self.key["client_email"]

    def token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        now = int(time.time())
        header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = b64url(json.dumps({
            "iss": self.key["client_email"], "scope": self.scope,
            "aud": self.key["token_uri"], "iat": now, "exp": now + 3600,
        }).encode())
        private_key = serialization.load_pem_private_key(self.key["private_key"].encode(), password=None)
        signature = private_key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": f"{header}.{claims}.{b64url(signature)}",
        }).encode()
        req = urllib.request.Request(self.key["token_uri"], data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"Google token endpoint returned HTTP {exc.code}: {detail}") from exc
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
        if meta["mimeType"].startswith("text/"):
            return self.request("GET", f"{API}/files/{meta['id']}", {"alt": "media"}, raw=True)
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
    parser.add_argument("command", choices=["check", "seed", "list", "read", "access", "share", "unshare"])
    parser.add_argument("target", nargs="*", help="file ID for read, user names for share/unshare")
    args = parser.parse_args()

    drive = GoogleDrive()
    folder = drive.folder()

    if args.command == "check":
        print(f"Signed in as {drive.email}; folder {folder['name']!r} ({folder['id']}) is visible")
        return

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
        perms = drive.permissions(folder["id"])
        for name in args.target:
            email = persona_email(name)
            existing = [p for p in perms if p["type"] == "user" and (p.get("emailAddress") or "").lower() == email]
            if args.command == "share":
                if existing:
                    print(f"{name} ({email}) already has {existing[0]['role']} access")
                    continue
                drive.request(
                    "POST", f"{API}/files/{folder['id']}/permissions", {"sendNotificationEmail": "false"},
                    payload={"type": "user", "role": "reader", "emailAddress": email},
                )
                print(f"Shared {folder['name']} with {name} ({email}) as reader")
            else:
                if not existing:
                    print(f"{name} ({email}) has no direct access to {folder['name']}")
                    continue
                if existing[0]["role"] == "owner":
                    raise RuntimeError(f"{name} owns the folder; ownership cannot be revoked here")
                drive.request("DELETE", f"{API}/files/{folder['id']}/permissions/{existing[0]['id']}", raw=True)
                print(f"Removed {name} ({email}) from {folder['name']}")
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

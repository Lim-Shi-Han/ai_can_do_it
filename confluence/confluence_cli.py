#!/usr/bin/env python3
"""Seed and inspect the hackathon Confluence space using REST API v2."""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from html.parser import HTMLParser


ROOT = Path(__file__).resolve().parent
SEED = ROOT / "seed_pages.json"
MANIFEST = ROOT / "page_manifest.json"
DEFAULT_SITE = "https://hackathontencent.atlassian.net"
SPACE_KEY = "PAYOPS"


def load_local_env():
    """Read simple KEY=VALUE secrets without executing shell code."""
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in {"ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "ATLASSIAN_CLOUD_ID", "CONFLUENCE_SITE_URL"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def load_seed():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    pages = data["pages"]
    if len(pages) != 8 or len({p["title"] for p in pages}) != 8:
        raise ValueError("Seed must contain eight uniquely titled pages")
    return data


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "h1", "h2", "h3", "li", "tr", "br"}:
            self.parts.append("\n")

    def text(self):
        return "\n".join(
            " ".join(line.split())
            for line in "".join(self.parts).splitlines()
            if line.strip()
        )


def storage_to_text(storage):
    parser = TextExtractor()
    parser.feed(storage or "")
    return parser.text()


class Confluence:
    def __init__(self):
        email = os.environ.get("ATLASSIAN_EMAIL")
        token = os.environ.get("ATLASSIAN_API_TOKEN")
        if not email or not token:
            raise ValueError("Set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN locally")
        self.site = os.environ.get("CONFLUENCE_SITE_URL", DEFAULT_SITE).rstrip("/")
        cloud_id = os.environ.get("ATLASSIAN_CLOUD_ID")
        self.api_base = (
            f"https://api.atlassian.com/ex/confluence/{cloud_id}"
            if cloud_id else self.site
        )
        basic = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Accept": "application/json", "Authorization": f"Basic {basic}"}

    def request(self, method, path, params=None, payload=None):
        if params:
            path += "?" + urllib.parse.urlencode(params)
        url = self.api_base + path
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"Confluence API returned HTTP {exc.code}: {detail}") from exc

    def pages(self, space_id):
        path = "/wiki/api/v2/pages?" + urllib.parse.urlencode(
            {"space-id": space_id, "status": "current", "limit": 100}
        )
        results = []
        while path:
            response = self.request("GET", path)
            results.extend(response.get("results", []))
            path = response.get("_links", {}).get("next")
        return results

    def space_id(self):
        response = self.request("GET", "/wiki/api/v2/spaces", {"keys": SPACE_KEY})
        spaces = [s for s in response.get("results", []) if s.get("key") == SPACE_KEY]
        if len(spaces) != 1:
            raise RuntimeError(f"Expected one visible space with key {SPACE_KEY}; got {len(spaces)}")
        return spaces[0]["id"]

    def page(self, page_id):
        return self.request("GET", f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})

    def page_url(self, page):
        links = page.get("_links", {})
        webui = links.get("webui")
        base = links.get("base", self.site + "/wiki")
        return base.rstrip("/") + webui if webui else f"{self.site}/wiki/pages/viewpage.action?pageId={page['id']}"


def save_manifest(api, space_id, pages, seed):
    by_title = {p["title"]: p for p in pages}
    entries = []
    for item in seed["pages"]:
        page = by_title.get(item["title"])
        if not page:
            raise RuntimeError(f"Missing seeded page: {item['title']}")
        entries.append({
            "slug": item["slug"],
            "id": page["id"],
            "title": page["title"],
            "url": api.page_url(page),
            "version": page.get("version", {}).get("number"),
            "updated_at": page.get("version", {}).get("createdAt"),
        })
    data = {
        "source": "confluence",
        "site": api.site,
        "space_key": SPACE_KEY,
        "space_id": str(space_id),
        "incident_id": seed["scenario"]["incident_id"],
        "pages": entries,
    }
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "check", "seed", "list", "read", "update-runbook"])
    parser.add_argument("page_id", nargs="?", help="Required for read")
    args = parser.parse_args()
    seed = load_seed()

    if args.command == "preview":
        print(f"Space: {SPACE_KEY}; incident: {seed['scenario']['incident_id']}")
        for page in seed["pages"]:
            print(f"- {page['title']}")
        return

    api = Confluence()
    space_id = api.space_id()
    if args.command == "check":
        print(f"Connected to {api.site}; space {SPACE_KEY} has ID {space_id}")
        return

    pages = api.pages(space_id)
    if args.command == "seed":
        by_title = {p["title"]: p for p in pages}
        for item in seed["pages"]:
            if item["title"] in by_title:
                print(f"Exists: {item['title']}")
                continue
            payload = {
                "spaceId": str(space_id),
                "status": "current",
                "title": item["title"],
                "body": {"representation": "storage", "value": item["html"]},
            }
            page = api.request("POST", "/wiki/api/v2/pages", payload=payload)
            print(f"Created: {item['title']} ({api.page_url(page)})")
        pages = api.pages(space_id)

    if args.command == "update-runbook":
        title = seed["runbook_update"]["title"]
        matches = [p for p in pages if p["title"] == title]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one runbook, found {len(matches)}")
        current = api.page(matches[0]["id"])
        new_body = seed["runbook_update"]["html"]
        if current.get("body", {}).get("storage", {}).get("value") == new_body:
            print("Runbook already contains the demo update")
        else:
            payload = {
                "id": current["id"],
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": new_body},
                "version": {
                    "number": current["version"]["number"] + 1,
                    "message": "Hackathon freshness demo: approved standby-region step",
                },
            }
            updated = api.request("PUT", f"/wiki/api/v2/pages/{current['id']}", payload=payload)
            print(f"Updated runbook to version {updated['version']['number']}")
        pages = api.pages(space_id)

    if args.command == "read":
        if not args.page_id:
            parser.error("read requires page_id")
        page = api.page(args.page_id)
        print(json.dumps({
            "id": page["id"],
            "title": page["title"],
            "url": api.page_url(page),
            "version": page["version"]["number"],
            "updated_at": page["version"].get("createdAt"),
            "text": storage_to_text(page.get("body", {}).get("storage", {}).get("value")),
        }, indent=2, ensure_ascii=False))
        return

    manifest = save_manifest(api, space_id, pages, seed)
    for page in manifest["pages"]:
        print(f"{page['id']} v{page['version']} {page['title']} — {page['url']}")
    print(f"Manifest saved to {MANIFEST}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

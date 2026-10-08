import math
from datetime import datetime, timezone

from confluence.confluence_cli import SPACE_KEY, Confluence, load_local_env, storage_to_text

from .base import Candidate, Doc, keywords


class ConfluenceSource:
    name = "confluence"

    def __init__(self, space_key=SPACE_KEY):
        load_local_env()
        self.api = Confluence()
        self.space_key = space_key

    def _cql(self, cql, limit):
        path = "/wiki/rest/api/content/search"
        params = {"cql": cql, "limit": min(limit, 100), "expand": "version"}
        out = []
        while path and len(out) < limit:
            response = self.api.request("GET", path, params)
            out.extend(
                Candidate(self.name, item["id"], item["title"], self.space_key,
                          item.get("version", {}).get("number"))
                for item in response.get("results", [])
            )
            path, params = response.get("_links", {}).get("next"), None
        return out[:limit]

    def search(self, query, incident_id=None, limit=10):
        terms = keywords(query)
        if incident_id:
            terms.insert(0, incident_id)
        if not terms:
            return []
        match = " or ".join(f'text ~ "{t}"' for t in terms)
        return self._cql(f'space="{self.space_key}" and type=page and ({match})', limit)

    def can_access(self, user, doc_id):
        account_id = user.get("atlassian_account_id")
        if not account_id:
            return False
        response = self.api.request(
            "POST",
            f"/wiki/rest/api/content/{doc_id}/permission/check",
            payload={"subject": {"type": "user", "identifier": account_id}, "operation": "read"},
        )
        return response.get("hasPermission") is True

    def fetch(self, doc_id):
        page = self.api.page(doc_id)
        return Doc(
            source=self.name,
            doc_id=page["id"],
            title=page["title"],
            url=self.api.page_url(page),
            version=page["version"]["number"],
            updated_at=page["version"].get("createdAt", ""),
            text=storage_to_text(page.get("body", {}).get("storage", {}).get("value")),
            container=self.space_key,
        )

    def changes_since(self, ts):
        cql = f'space="{self.space_key}" and type=page'
        if ts:
            # relative dates avoid CQL's dependence on the account's profile timezone
            since = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            minutes = math.ceil((datetime.now(timezone.utc) - since).total_seconds() / 60) + 1
            cql += f' and lastmodified >= now("-{minutes}m")'
        return self._cql(cql, 1000)

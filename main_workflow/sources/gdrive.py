from gdrive.gdrive_cli import READ_SCOPE, GoogleDrive, load_local_env

from .base import Candidate, Doc, keywords


def quote(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GDriveSource:
    name = "gdrive"

    def __init__(self):
        load_local_env()
        self.api = GoogleDrive(scope=READ_SCOPE)
        self._folder_names = {}

    def _container(self, parents):
        if not parents:
            return ""
        folder_id = parents[0]
        if folder_id not in self._folder_names:
            try:
                self._folder_names[folder_id] = self.api.file(folder_id)["name"]
            except RuntimeError:
                self._folder_names[folder_id] = folder_id
        return self._folder_names[folder_id]

    def _candidates(self, q):
        return [
            Candidate(self.name, f["id"], f["name"], self._container(f.get("parents")), int(f.get("version", 0)))
            for f in self.api.list_files(f"({q}) and trashed = false and mimeType != 'application/vnd.google-apps.folder'")
        ]

    def search(self, query, incident_id=None, limit=10):
        terms = keywords(query)
        if incident_id:
            terms.insert(0, incident_id)
        if not terms:
            return []
        q = " or ".join(f"fullText contains '{quote(t)}'" for t in terms)
        return self._candidates(q)[:limit]

    def can_access(self, user, doc_id):
        email = (user.get("google_email") or "").lower()
        if not email:
            return False
        domain = email.rsplit("@", 1)[-1]
        for p in self.api.permissions(doc_id):
            if p.get("deleted"):
                continue
            if p["type"] == "anyone":
                return True
            if p["type"] == "user" and (p.get("emailAddress") or "").lower() == email:
                return True
            if p["type"] == "domain" and (p.get("domain") or "").lower() == domain:
                return True
            # group membership would need the Admin SDK; share with individuals instead
        return False

    def fetch(self, doc_id):
        meta = self.api.file(doc_id)
        if meta.get("trashed"):
            raise RuntimeError(f"Drive file {doc_id} is in the trash")
        return Doc(
            source=self.name,
            doc_id=meta["id"],
            title=meta["name"],
            url=meta.get("webViewLink", f"https://drive.google.com/file/d/{doc_id}/view"),
            version=int(meta.get("version", 0)),
            updated_at=meta.get("modifiedTime", ""),
            text=self.api.text(meta).strip(),
            container=self._container(meta.get("parents")),
        )

    def changes_since(self, ts):
        return self._candidates(f"modifiedTime > '{ts}'" if ts else "trashed = false")

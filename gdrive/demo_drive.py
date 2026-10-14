#!/usr/bin/env python3
"""Set up Company A's Google Drive for the demo: folders, who can open them, and each person's files.

The service account reads files, checks who can open them, and shares folders, but cannot create files (it has
no storage). Files are created with each owner's own Google sign-in (gdrive_cli.py login NAME):

    python3 gdrive/demo_drive.py seed                        # folders as Zhao, sharing, every standing file as its owner
    python3 gdrive/demo_drive.py upload STEP [NAME]          # during the demo: that step's files, uploaded as their owners
    python3 gdrive/demo_drive.py check                       # every file present, owned by the right person, readable
    python3 gdrive/demo_drive.py access                      # who can open each file, according to Drive
    python3 gdrive/demo_drive.py reset [--yes]               # before a rehearsal: remove Terrance, clear the processor folder

Without sign-ins, people upload by hand instead:

    python3 gdrive/demo_drive.py build [--date YYYY-MM-DD]   # the files to upload, one folder per person, in gdrive/upload/
    python3 gdrive/demo_drive.py setup                       # after Zhao's upload: sharing, the processor folder, the old report
"""

import argparse
import io
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from gdrive.gdrive_cli import (  # noqa: E402
    API, FOLDER, IDENTITIES, GoogleDrive, create_folder, load_local_env, persona_email, share, token_path, unshare,
    upload_file,
)

SPEC = ROOT / "demo_drive.json"
UPLOAD = ROOT / "upload"
SGT = timezone(timedelta(hours=8))
FIELDS = "id,name,mimeType,parents,owners(emailAddress),modifiedTime,webViewLink"


def load_spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- files

def runs(text, bold=False):
    """'**bold**' spans as bold runs."""
    out = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if part:
            props = "<w:rPr><w:b/></w:rPr>" if bold or i % 2 else ""
            out.append(f'<w:r>{props}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return "".join(out)


def paragraph(text, style=None, bold=False):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}{runs(text, bold)}</w:p>"


def table(rows):
    cols = max(len(r) for r in rows)
    width = 9638 // cols
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(cols))
    body = "".join(
        "<w:tr>" + "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>{paragraph(cell, bold=n == 0)}</w:tc>'
            for cell in row + [""] * (cols - len(row))
        ) + "</w:tr>"
        for n, row in enumerate(rows)
    )
    return (f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>")


XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
BORDER = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
STYLES = XML + (
    f"<w:styles {W_NS}>"
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="21"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="60"/><w:ind w:left="360" w:hanging="240"/></w:pPr></w:style>'
    '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
    + "".join(BORDER.format(side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    + '</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
    "</w:styles>"
)
CONTENT_TYPES = XML + (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    "</Types>"
)
PACKAGE_RELS = XML + (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    "</Relationships>"
)
DOCUMENT_RELS = XML + (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{REL}/styles" Target="styles.xml"/></Relationships>'
)


def docx(lines, author, written):
    """A Word file from the spec's text format: '# ' title, '## ' headings, '- ' bullets, '1. ' items,
    '| a | b |' table rows (the first row is the header), '**bold**', and plain lines as paragraphs."""
    blocks, rows = [], []
    for line in lines + [""]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if rows:
            blocks.append(table(rows))
            rows = []
        if line.startswith("# "):
            blocks.append(paragraph(line[2:], "Title"))
        elif line.startswith("## "):
            blocks.append(paragraph(line[3:], "Heading1"))
        elif line.startswith("- "):
            blocks.append(paragraph("• " + line[2:], "ListBullet"))
        elif re.match(r"\d+\. ", line):
            blocks.append(paragraph(line, "ListBullet"))
        elif line.strip():
            blocks.append(paragraph(line))
    page = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
            'w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
    document = XML + f"<w:document {W_NS}><w:body>{''.join(blocks)}<w:p/>{page}</w:body></w:document>"
    stamp = f"{written}T09:00:00Z"
    title = next((l[2:] for l in lines if l.startswith("# ")), "")
    core = XML + (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>"
        f"<cp:lastModifiedBy>{escape(author)}</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified></cp:coreProperties>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", CONTENT_TYPES), ("_rels/.rels", PACKAGE_RELS),
                           ("word/document.xml", document), ("word/_rels/document.xml.rels", DOCUMENT_RELS),
                           ("word/styles.xml", STYLES), ("docProps/core.xml", core)):
            z.writestr(name, data)
    return buffer.getvalue()


def render(item, date):
    """The file's bytes for the given rehearsal date."""
    lines = [line.replace("{date}", date) for line in item["lines"]]
    if item["name"].endswith(".docx"):
        return docx(lines, item["owner"], item.get("written", date))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def upload_path(spec, item, date=None):
    root = spec["root"]
    if date:  # a file created during the demo
        return UPLOAD / f"3 demo {date}" / f"step {item['step']} - {item['owner']}" / item["name"].replace("{date}", date)
    if item["owner"] == spec["owner"]:
        return UPLOAD / f"1 {item['owner']} - drag the {root} folder into My Drive" / root / item["folder"] / item["name"]
    return UPLOAD / f"2 {item['owner']}" / f"into {root} - {item['folder'].replace('/', ' - ')}" / item["name"]


def build(spec, date, robot):
    if UPLOAD.exists():
        shutil.rmtree(UPLOAD)
    for item in spec["files"]:
        path = upload_path(spec, item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render(item, date))
    for item in spec["live"]:
        path = upload_path(spec, item, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render(item, date))
    exchange = next(f["path"] for f in spec["folders"] if f.get("exchange")).replace("/", " > ")
    owners = sorted({f["owner"] for f in spec["files"]} - {spec["owner"]})
    steps = [
        f"How to upload Company A's Drive files (built for {date})",
        "",
        "Turn OFF 'Convert uploads' in Drive settings so the files stay Word and CSV files.",
        "",
        f"1. {spec['owner']}: in drive.google.com, drag the '{spec['root']}' folder from '1 {spec['owner']} - ...' into My Drive.",
        f"   Then share '{spec['root']}' with {robot} as Editor (untick 'Notify people').",
        "",
        "2. Tell whoever runs the scripts. They run: python gdrive/demo_drive.py setup",
        "   This shares each folder with the right people and moves the processor folder into place.",
        "",
        f"3. {', '.join(owners)}: open 'Shared with me' > '{spec['root']}', open the folder named in your '2 <name>' folder",
        "   (for example 'into Company A - Finance' means Company A > Finance), and drag the FILES in, not the folder.",
        "",
        "4. Whoever runs the scripts: python gdrive/demo_drive.py setup   (again, for the one file shared on its own)",
        "                            python gdrive/demo_drive.py check",
        "",
        f"During the demo, the files in '3 demo {date}' are uploaded live into {spec['root']} > {exchange}",
        "by the person named in each folder, at the step named in each folder.",
    ]
    (UPLOAD / "HOW TO UPLOAD.txt").write_text("\n".join(steps) + "\n", encoding="utf-8")
    return steps


# ---------------------------------------------------------------- Drive

def quote(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def people():
    users = json.loads(IDENTITIES.read_text(encoding="utf-8"))["users"]
    return {u["google_email"].lower(): u["name"] for u in users if u.get("google_email")}


def owner_name(item, names):
    emails = [o.get("emailAddress", "").lower() for o in item.get("owners", [])]
    return next((names.get(e, e) for e in emails), "?")


def children(drive, folder, name=None):
    q = f"'{folder['id']}' in parents and trashed = false"
    if name:
        q += f" and name = '{quote(name)}'"
    return drive.list_files(q, FIELDS)


def find_root(drive, spec, names):
    owner = persona_email(spec["owner"])
    q = f"name = '{quote(spec['root'])}' and mimeType = '{FOLDER}' and trashed = false"
    found = [f for f in drive.list_files(q, FIELDS) if any(o.get("emailAddress", "").lower() == owner for o in f.get("owners", []))]
    if not found:
        raise ValueError(f"No folder '{spec['root']}' owned by {spec['owner']} is shared with {drive.email}. "
                         f"Run build, have {spec['owner']} upload it, and share it with the service account as Editor.")
    if len(found) > 1:
        raise RuntimeError(f"{len(found)} folders named '{spec['root']}' owned by {spec['owner']}; keep one")
    return found[0]


def resolve(drive, spec, names, adopt=False):
    """Map each folder path in the spec to its Drive folder; with adopt, move the processor folder into place."""
    folders, notes = {"": find_root(drive, spec, names)}, []
    for entry in spec["folders"]:
        parent_path, _, name = entry["path"].rpartition("/")
        parent = folders.get(parent_path)
        if parent is None:
            continue
        found = [f for f in children(drive, parent, name) if f["mimeType"] == FOLDER]
        if not found and entry.get("exchange") and adopt:
            found = [f for f in [adopt_exchange(drive, parent, name)] if f]
        if not found:
            notes.append(f"MISSING folder {spec['root']}/{entry['path']}: {spec['owner']} creates it in Drive, "
                         f"empty, then run setup again")
            continue
        if len(found) > 1:
            notes.append(f"{len(found)} folders named {entry['path']}; using the first")
        folders[entry["path"]] = found[0]
        if owner_name(found[0], names) != spec["owner"]:
            notes.append(f"{entry['path']} is owned by {owner_name(found[0], names)}, not {spec['owner']}")
    return folders, notes


def adopt_exchange(drive, parent, name):
    """The existing GDRIVE_FOLDER_ID folder becomes the processor folder, so .env keeps working.
    None if there is no usable folder to adopt."""
    if not drive.folder_id:
        return None
    try:
        current = drive.request("GET", f"{API}/files/{drive.folder_id}", {"fields": FIELDS + ",trashed"})
    except RuntimeError:
        return None
    if current.get("trashed") or current.get("mimeType") != FOLDER:
        return None
    params = {"fields": FIELDS}
    if parent["id"] not in current.get("parents", []):
        params.update(addParents=parent["id"], removeParents=",".join(current.get("parents", [])))
    moved = drive.request("PATCH", f"{API}/files/{current['id']}", params, payload={"name": name})
    print(f"Moved folder '{current['name']}' into {parent['name']} and renamed it '{name}'")
    return moved


def setup(drive, spec):
    names = people()
    folders, notes = resolve(drive, spec, names, adopt=True)
    for entry in spec["folders"]:
        folder = folders.get(entry["path"])
        for name, role in entry["share"].items():
            if folder:
                print(share(drive, folder, name, role))

    for title in spec["trash"]:
        for item in drive.list_files(f"name = '{quote(title)}' and trashed = false", FIELDS):
            try:
                drive.request("PATCH", f"{API}/files/{item['id']}", payload={"trashed": True})
                print(f"Moved '{title}' to the trash (owner {owner_name(item, names)} can restore it for 30 days)")
            except RuntimeError as exc:
                notes.append(f"{owner_name(item, names)} must delete '{title}' in Drive before step 3, "
                             f"or the processor will see it ({str(exc)[:60]})")

    for item in spec["files"]:
        if not item.get("share") or item["folder"] not in folders:
            continue
        found = children(drive, folders[item["folder"]], item["name"])
        for name, role in item["share"].items():
            print(share(drive, found[0], name, role) if found
                  else f"Not uploaded yet: {item['name']} (shared with {name} once {item['owner']} uploads it)")

    exchange = next((folders.get(e["path"]) for e in spec["folders"] if e.get("exchange")), None)
    if exchange and exchange["id"] != drive.folder_id:
        notes.append(f"Set GDRIVE_FOLDER_ID={exchange['id']} in .env (the folder shared with the processor)")
    for note in notes:
        print(f"! {note}")


def check(drive, spec):
    names = people()
    folders, notes = resolve(drive, spec, names)
    ok = not notes
    for note in notes:
        print(f"! {note}")
    expected = {}
    for item in spec["files"]:
        expected.setdefault(item["folder"], set()).add(item["name"])
        folder = folders.get(item["folder"])
        found = children(drive, folder, item["name"]) if folder else []
        if not found:
            print(f"MISSING   {item['owner']:<8} {item['folder']}/{item['name']}")
            ok = False
            continue
        owner, expected_owner = owner_name(found[0], names), uploader(spec, item["owner"])
        size = len(drive.text(found[0]))
        good = owner == expected_owner and size > 50
        ok &= good
        note = "" if expected_owner == item["owner"] else f"  (uploaded by {expected_owner})"
        problem = "" if good else (f"  owner is {owner}" if owner != expected_owner else "  no readable text")
        print(f"{'ok' if good else 'WRONG':<9} {item['owner']:<8} {item['folder']}/{item['name']}  ({size} chars){note}{problem}")
    live = [re.compile(re.escape(f["name"]).replace(re.escape("{date}"), r"\d{4}-\d{2}-\d{2}") + "$") for f in spec["live"]]
    for entry in spec["folders"]:
        folder = folders.get(entry["path"])
        subfolders = {e["path"].rpartition("/")[2] for e in spec["folders"] if e["path"].rpartition("/")[0] == entry["path"]}
        for item in children(drive, folder) if folder else []:
            where = f"{owner_name(item, names):<8} {entry['path']}/{item['name']}"
            if entry.get("exchange") and any(p.match(item["name"]) for p in live):
                print(f"demo      {where}")  # uploaded during a rehearsal
            elif item["name"] not in expected.get(entry["path"], set()) | subfolders:
                # anything else in the processor folder is visible to the processor from step 3
                print(f"EXTRA     {where}" + ("  (the processor would see this)" if entry.get("exchange") else ""))
                ok &= not entry.get("exchange")
    for title in spec["trash"]:
        for item in drive.list_files(f"name = '{quote(title)}' and trashed = false", FIELDS):
            print(f"! '{title}' still exists; {owner_name(item, names)} must delete it")
            ok = False
    problems = sharing_problems(drive, spec, folders, names)
    for problem in problems:
        print(f"! {problem}")
    ok &= not any(p for p in problems if "during the demo" not in p)
    print("All files are in place." if ok else "Some files are missing or wrong.")
    return ok


def sharing_problems(drive, spec, folders, names):
    """Differences between who can open each folder and the spec (shares reach every folder below)."""
    rank = {"reader": 1, "commenter": 2, "writer": 3}
    labels = {"reader": "viewer", "commenter": "commenter", "writer": "editor"}
    guest = next(f["owner"] for f in spec["live"] if f["step"] == 3)
    expected, problems, unknown = {"": {}}, [], set()
    for entry in spec["folders"]:
        inherited = dict(expected[entry["path"].rpartition("/")[0]])
        for name, role in entry["share"].items():
            api_role = {"viewer": "reader", "commenter": "commenter", "editor": "writer"}[role]
            if rank[api_role] > rank.get(inherited.get(name), 0):
                inherited[name] = api_role
        expected[entry["path"]] = inherited
    for path, want in expected.items():
        folder = folders.get(path)
        if not folder:
            continue
        actual = {}
        where = f"{spec['root']}/{path}".rstrip("/")
        for p in drive.permissions(folder["id"]):
            email = (p.get("emailAddress") or "").lower()
            name = names.get(email)
            if name and name != spec["owner"] and p["role"] != "owner":
                actual[name] = p["role"]
            elif not name and email != drive.email.lower() and p["role"] != "owner" and email not in unknown:
                # e.g. someone's previous Google account after identities.json changed; reported at the top folder only
                unknown.add(email)
                problems.append(f"{email or p['type']} can open {where} but is not anyone in identities.json")
        exchange = any(e.get("exchange") and e["path"] == path for e in spec["folders"])
        for name in sorted(set(actual) | set(want)):
            if actual.get(name) == want.get(name):
                continue
            if exchange and name == guest and name not in want:
                problems.append(f"{guest} can open {where}: expected during the demo (steps 3 to 8); run reset before a rehearsal")
            elif name not in want:
                problems.append(f"{name} can open {where} ({labels.get(actual[name], actual[name])}) but should not")
            else:
                problems.append(f"{name} has {labels.get(actual.get(name), 'no')} access to {where}, should be {labels[want[name]]}")
    return problems


def access(drive, spec):
    names = people()
    folders, notes = resolve(drive, spec, names)
    for note in notes:
        print(f"! {note}")
    cast = sorted(set(names.values()))
    print(f"{'':<70}" + "".join(f"{n[:8]:<9}" for n in cast))
    for entry in spec["folders"]:
        folder = folders.get(entry["path"])
        for item in [folder] + [c for c in children(drive, folder) if c["mimeType"] != FOLDER] if folder else []:
            perms = drive.permissions(item["id"])
            emails = {(p.get("emailAddress") or "").lower() for p in perms if p["type"] == "user" and not p.get("deleted")}
            everyone = any(p["type"] in ("anyone", "domain") for p in perms)
            label = (entry["path"] + "/" if item is folder else "  ") + ("" if item is folder else item["name"])
            print(f"{label[:69]:<70}" + "".join(f"{'yes' if everyone or persona_email(n) in emails else '.':<9}" for n in cast))


SIGN_INS = {}


def uploader(spec, owner):
    """Who uploads owner's files: the owner, unless the spec names a stand-in because they cannot sign in."""
    return spec.get("uploaded_by", {}).get(owner, owner)


def person(name):
    """name's own Google sign-in from gdrive_cli.py login, or None if they have not signed in."""
    if name not in SIGN_INS:
        SIGN_INS[name] = GoogleDrive(user=name) if token_path(name).exists() else None
    return SIGN_INS[name]


def seed(robot, spec, date, fix_owners=False):
    """Create what is missing: the folder tree as Zhao, the sharing as the service account, each file as its owner.
    With fix_owners, a file uploaded by the wrong person is uploaded again by its owner and the old copy trashed."""
    names = people()
    owner = person(spec["owner"])
    if not owner:
        raise ValueError(f"{spec['owner']} owns the folders; first run: python gdrive/gdrive_cli.py login {spec['owner']}")

    q = f"name = '{quote(spec['root'])}' and mimeType = '{FOLDER}' and 'me' in owners and trashed = false"
    roots = owner.list_files(q, FIELDS)
    if len(roots) > 1:
        raise RuntimeError(f"{spec['owner']} has {len(roots)} folders named '{spec['root']}'; keep one")
    root = roots[0] if roots else create_folder(owner, "root", spec["root"])
    if not roots:
        print(f"{spec['owner']} created folder {spec['root']}")
    if not any((p.get("emailAddress") or "").lower() == robot.email.lower() for p in owner.permissions(root["id"])):
        owner.request("POST", f"{API}/files/{root['id']}/permissions", {"sendNotificationEmail": "false"},
                      payload={"type": "user", "role": "writer", "emailAddress": robot.email})
        print(f"{spec['owner']} shared {spec['root']} with the service account as editor")
    # a share on the top folder would reach every folder below it, so people get access folder by folder instead
    for p in owner.permissions(root["id"]):
        name = names.get((p.get("emailAddress") or "").lower())
        if name and name != spec["owner"] and p["role"] != "owner":
            print(unshare(owner, root, name))

    # folder IDs come from the owner's own calls, so nothing waits for Drive's search to catch up
    paths = {"": root}
    for entry in spec["folders"]:
        parent_path, _, name = entry["path"].rpartition("/")
        found = [f for f in children(owner, paths[parent_path], name) if f["mimeType"] == FOLDER]
        paths[entry["path"]] = found[0] if found else create_folder(owner, paths[parent_path]["id"], name)
        if not found:
            print(f"{spec['owner']} created folder {spec['root']}/{entry['path']}")
    for entry in spec["folders"]:
        for name, role in entry["share"].items():
            print(share(robot, paths[entry["path"]], name, role))

    files = {}
    for item in spec["files"]:
        where = f"{item['folder']}/{item['name']}"
        existing = children(owner, paths[item["folder"]], item["name"])
        expected = uploader(spec, item["owner"])
        client = person(expected)
        on_behalf = "" if expected == item["owner"] else f" for {item['owner']}"
        if existing:
            who = owner_name(existing[0], names)
            files[item["name"]] = existing[0]
            current = person(who) if who in names.values() else None
            if who == expected:
                print(f"Already there: {where} ({who}{on_behalf})")
            elif fix_owners and client and current:
                # upload the owner's copy first, so the file is never missing
                files[item["name"]] = upload_file(client, paths[item["folder"]]["id"], item["name"], render(item, date))
                current.request("PATCH", f"{API}/files/{existing[0]['id']}", payload={"trashed": True})
                print(f"{expected} uploaded {where}{on_behalf}; {who}'s copy moved to {who}'s trash")
            else:
                print(f"WRONG owner: {where} is {who}'s, should be {expected}'s; " + (
                    "run seed --fix-owners" if client and current else f"{expected} must sign in first"))
            continue
        if not client:
            print(f"Skipped {where}: {expected} has not signed in (python gdrive/gdrive_cli.py login {expected})")
            continue
        files[item["name"]] = upload_file(client, paths[item["folder"]]["id"], item["name"], render(item, date))
        print(f"{expected} uploaded {where}{on_behalf}")
    for item in spec["files"]:
        for name, role in item.get("share", {}).items():
            if item["name"] in files:
                print(share(robot, files[item["name"]], name, role))

    exchange = next(paths[e["path"]] for e in spec["folders"] if e.get("exchange"))
    if exchange["id"] != robot.folder_id:
        print(f"! Set GDRIVE_FOLDER_ID={exchange['id']} in .env (the folder shared with the processor)")


def exchange_folder(drive, spec):
    """The folder shared with the processor: GDRIVE_FOLDER_ID when it is that folder, otherwise found by path."""
    path = next(e["path"] for e in spec["folders"] if e.get("exchange"))
    if drive.folder_id:
        try:
            meta = drive.request("GET", f"{API}/files/{drive.folder_id}", {"fields": FIELDS + ",trashed"})
            if meta["name"] == path.rpartition("/")[2] and not meta.get("trashed"):
                return meta
        except RuntimeError:
            pass
    folders, _ = resolve(drive, spec, people())
    if path not in folders:
        raise RuntimeError("The processor folder is missing; run seed first")
    return folders[path]


def upload(robot, spec, step, who, date):
    """A live demo upload: the step's files, each uploaded with its owner's sign-in into the processor folder."""
    items = [f for f in spec["live"] if f["step"] == step and who in (None, f["owner"])]
    if not items:
        raise ValueError(f"No demo file for step {step}" + (f" by {who}" if who else "") +
                         f"; the demo files are: " + ", ".join(f"step {f['step']} {f['owner']}" for f in spec["live"]))
    exchange = exchange_folder(robot, spec)
    for item in items:
        name = item["name"].replace("{date}", date)
        if children(robot, exchange, name):
            print(f"Already uploaded: {name}")
            continue
        by = uploader(spec, item["owner"])
        client = person(by)
        if not client:
            raise ValueError(f"{by} has not signed in; run: python gdrive/gdrive_cli.py login {by}")
        try:
            upload_file(client, exchange["id"], name, render(item, date))
        except RuntimeError as exc:
            if "HTTP 403" in str(exc) or "HTTP 404" in str(exc):
                raise RuntimeError(f"Drive refused: {by} cannot add files to '{exchange['name']}'. "
                                   f"Share the folder with {by} as editor first.") from exc
            raise
        print(f"{by} uploaded {name} to {exchange['name']}" + ("" if by == item["owner"] else f" for {item['owner']}"))


def reset(drive, spec, confirm):
    names = people()
    exchange = exchange_folder(drive, spec)
    guest = next(f["owner"] for f in spec["live"] if f["step"] == 3)
    print(unshare(drive, exchange, guest))
    for item in children(drive, exchange):
        owner = owner_name(item, names)
        if not confirm:
            print(f"Would remove {item['name']} ({owner}); rerun with --yes")
            continue
        # only the owner can trash a file; use their sign-in when there is one
        client = (person(owner) if owner in names.values() else None) or drive
        try:
            client.request("PATCH", f"{API}/files/{item['id']}", payload={"trashed": True})
            print(f"Moved {item['name']} to {owner}'s trash")
        except RuntimeError:
            print(f"{owner} must delete '{item['name']}' in Drive (only the owner can, and {owner} has not signed in)")


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["seed", "upload", "check", "access", "reset", "build", "setup"])
    parser.add_argument("target", nargs="*", help="upload: STEP and optionally the uploader's NAME")
    parser.add_argument("--date", default=datetime.now(SGT).date().isoformat(), help="the rehearsal date in the demo files")
    parser.add_argument("--yes", action="store_true", help="reset: also trash the files in the processor folder")
    parser.add_argument("--fix-owners", action="store_true", help="seed: have each owner upload their own copy of a file "
                                                                  "someone else uploaded, and trash the other copy")
    args = parser.parse_args()
    spec = load_spec()

    if args.command == "build":
        drive = GoogleDrive()
        for line in build(spec, args.date, drive.email):
            print(line)
        print(f"\nFiles written to {UPLOAD}")
        return

    drive = GoogleDrive()
    if args.command == "upload":
        if not args.target or not args.target[0].isdigit() or len(args.target) > 2:
            parser.error("upload needs a step number and optionally a name, e.g. upload 7 Sheldon")
        upload(drive, spec, int(args.target[0]), args.target[1] if len(args.target) > 1 else None, args.date)
    elif args.command == "seed":
        seed(drive, spec, args.date, args.fix_owners)
    elif args.command == "setup":
        setup(drive, spec)
    elif args.command == "check":
        sys.exit(0 if check(drive, spec) else 1)
    elif args.command == "access":
        access(drive, spec)
    else:
        reset(drive, spec, args.yes)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

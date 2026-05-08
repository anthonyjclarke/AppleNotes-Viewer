#!/usr/bin/env python3
"""Notes Viewer — local HTTP server"""

import json
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

BASE_DIR   = Path(__file__).parent
NOTES_ROOT = BASE_DIR / "Notes"
APP_HTML   = BASE_DIR / "app.html"
PORT       = 8765

# Friendly account name for direct subfolders of NOTES_ROOT
# ("On My Mac - MASTER ARCHIVE" → "On My Mac")
ACCOUNT_SELF = re.sub(r'\s*[-–]\s*(MASTER\s+)?ARCHIVE\s*$', '', NOTES_ROOT.name, flags=re.I).strip()

# Directory names that contain assets, not notes
_ASSET_DIRS = {"images", "attachments"}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".pdf":  "application/pdf",
    ".js":   "application/javascript",
    ".css":  "text/css",
}


class NoteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.body_parts = []
        self._in_head = False
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":   self._in_head  = True
        if tag == "title":  self._in_title = True
        if tag == "h1":     self._in_h1    = True

    def handle_endtag(self, tag):
        if tag == "head":   self._in_head  = False
        if tag == "title":  self._in_title = False
        if tag == "h1":     self._in_h1    = False

    def handle_data(self, data):
        s = data.strip()
        if self._in_title:
            self.title = s
        elif not self._in_head and not self._in_h1 and s:
            self.body_parts.append(s)

    def body_text(self):
        return " ".join(self.body_parts)


# Match hashtags preceded by whitespace or start-of-string.
# Requires at least 3 chars and must start with a letter so hex colour
# codes (#e4afa0) and numeric anchors (#123) are excluded.
_TAG_RE = re.compile(r'(?:^|\s)#([A-Za-z][A-Za-z0-9]{2,})')
# Known false-positives that slip through (HTML attributes, URL params)
_TAG_BLOCKLIST = {"heading", "slide", "gid", "vis", "showing", "sthash",
                  "providers", "dashboard", "exec"}

def extract_tags(text: str) -> set:
    tags = set()
    for m in _TAG_RE.findall(text):
        low = m.lower()
        if low in _TAG_BLOCKLIST:
            continue
        # Skip anything that looks like a hex colour (all hex chars, 6-8 long)
        if all(c in "0123456789abcdefABCDEF" for c in m) and 6 <= len(m) <= 8:
            continue
        tags.add("#" + m)
    return tags



def build_index():
    notes = []
    for html_file in NOTES_ROOT.rglob("*.html"):
        parts = html_file.relative_to(NOTES_ROOT).parts

        # Skip HTML files that live inside asset directories (images, attachments)
        if any(p in _ASSET_DIRS for p in parts[:-1]):
            continue

        # folder = full parent path relative to NOTES_ROOT, e.g.
        #   "Archived"          for On My Mac notes
        #   "iCloud/Notes"      for iCloud notes
        folder = "/".join(parts[:-1]) or "Notes"

        try:
            raw = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        p = NoteParser()
        p.feed(raw)

        title = p.title.strip() if p.title else ""
        if not title:
            # Fall back to filename, stripping the date suffix
            title = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", html_file.stem).strip()

        date = datetime.fromtimestamp(html_file.stat().st_mtime)
        body = p.body_text()
        snippet = body[:280].strip()
        tags = extract_tags(title + " " + body)

        # _search: full lowercase text for server-side search
        # _path: absolute path for serving the file
        # _tags: set of hashtag strings found in this note
        notes.append({
            "file":    html_file.name,
            "folder":  folder,
            "title":   title,
            "date":    date.strftime("%Y-%m-%d"),
            "snippet": snippet,
            "_search": (title + " " + body).lower(),
            "_path":   str(html_file),
            "_tags":   tags,
        })

    notes.sort(key=lambda n: n["date"], reverse=True)
    return notes


print("Indexing notes…", end="", flush=True)
ALL_NOTES = build_index()
CLIENT_INDEX = [{k: v for k, v in n.items() if not k.startswith("_")} for n in ALL_NOTES]
FOLDERS = sorted({n["folder"] for n in ALL_NOTES})

# Build tag frequency table (tag → number of notes containing it)
_tag_counts: dict[str, int] = {}
for _n in ALL_NOTES:
    for _t in _n["_tags"]:
        _tag_counts[_t] = _tag_counts.get(_t, 0) + 1
# Sort: most-used first, then alphabetical; drop tags that appear in only 1 note
TAGS = [
    {"tag": t, "count": c}
    for t, c in sorted(_tag_counts.items(), key=lambda x: (-x[1], x[0].lower()))
    if c >= 2
]

print(f" {len(ALL_NOTES)} notes · {len(FOLDERS)} folder(s) · {len(TAGS)} tags.")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silent

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._file(APP_HTML, "text/html; charset=utf-8")

        elif path == "/api/notes":
            folder = qs.get("folder", [""])[0]
            if folder and folder != "__all__":
                data = [n for n in CLIENT_INDEX if n["folder"] == folder]
            else:
                data = CLIENT_INDEX
            self._json(data)

        elif path == "/api/search":
            q      = qs.get("q", [""])[0].strip().lower()
            folder = qs.get("folder", [""])[0]
            pool   = ALL_NOTES if not folder or folder == "__all__" else [n for n in ALL_NOTES if n["folder"] == folder]
            if len(q) < 2:
                results = [{k: v for k, v in n.items() if not k.startswith("_")} for n in pool]
            else:
                results = [
                    {k: v for k, v in n.items() if not k.startswith("_")}
                    for n in pool
                    if q in n["_search"]
                ]
            self._json(results)

        elif path == "/api/note":
            fname = unquote(qs.get("file", [""])[0])
            if fname and ".." not in fname:
                # Look up in index for the actual path
                match = next((n for n in ALL_NOTES if n["file"] == fname), None)
                if match:
                    self._file(Path(match["_path"]), "text/html; charset=utf-8")
                    return
            self.send_error(404)

        elif path == "/api/folders":
            # Count notes per folder path
            folder_counts: dict[str, int] = {}
            for n in ALL_NOTES:
                folder_counts[n["folder"]] = folder_counts.get(n["folder"], 0) + 1

            # Group by account (first path component)
            groups_map: dict[str, list] = {}
            for fpath in sorted(folder_counts):
                segs = fpath.split("/")
                if len(segs) == 1:
                    group = ACCOUNT_SELF          # e.g. "On My Mac"
                    name  = segs[0]
                else:
                    group = segs[0]               # e.g. "iCloud"
                    name  = "/".join(segs[1:])    # e.g. "Notes"
                is_del = name.lower() in ("recently deleted", "trash", "deleted items")
                groups_map.setdefault(group, []).append({
                    "name": name, "path": fpath,
                    "count": folder_counts[fpath], "deleted": is_del,
                })

            # Sort groups: ACCOUNT_SELF first, then alphabetical
            groups = [
                {"label": g, "folders": flds}
                for g, flds in sorted(groups_map.items(),
                                      key=lambda kv: (0 if kv[0] == ACCOUNT_SELF else 1, kv[0]))
            ]
            self._json({"total": len(ALL_NOTES), "groups": groups})

        elif path == "/api/tags":
            self._json(TAGS)

        elif path.startswith("/static/"):
            # /static/{folder}/{sub}/{file}
            rel = unquote(path[8:])
            if ".." not in rel:
                fp = NOTES_ROOT / rel
                if fp.is_file():
                    self._file(fp, MIME.get(fp.suffix.lower(), "application/octet-stream"))
                    return
            self.send_error(404)

        else:
            self.send_error(404)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            data = Path(path).read_bytes()
        except Exception:
            self.send_error(500)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    httpd = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"  → http://127.0.0.1:{PORT}")
    print("    Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

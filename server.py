#!/usr/bin/env python3
"""Notes Viewer — local HTTP server"""

import json
import re
import subprocess
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

BASE_DIR = Path(__file__).parent
APP_HTML = BASE_DIR / "app.html"
PORT     = 8765

_CONFIG_FILE  = BASE_DIR / "config.json"
_SKIP_FOLDERS = {"Recently Deleted"}   # Apple Notes folders excluded from index

MIME = {
    ".html": "text/html; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".pdf":  "application/pdf",
    ".js":   "application/javascript",
    ".css":  "text/css",
}


# ── HTML parser ──────────────────────────────────────────────────────────

class NoteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title      = ""
        self.modified   = ""      # <meta name="modified"> content
        self.body_parts = []
        self._in_head   = False
        self._in_title  = False
        self._in_h1     = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":  self._in_head  = True
        if tag == "title": self._in_title = True
        if tag == "h1":    self._in_h1    = True
        if tag == "meta":
            attr_d = dict(attrs)
            if attr_d.get("name") == "modified":
                self.modified = attr_d.get("content", "")

    def handle_endtag(self, tag):
        if tag == "head":  self._in_head  = False
        if tag == "title": self._in_title = False
        if tag == "h1":    self._in_h1    = False

    def handle_data(self, data):
        s = data.strip()
        if self._in_title:
            self.title = s
        elif not self._in_head and not self._in_h1 and s:
            self.body_parts.append(s)

    def body_text(self):
        return " ".join(self.body_parts)


# ── Tag extraction ───────────────────────────────────────────────────────

# Match hashtags that are not preceded by a word character (avoids URL fragments).
# Two alternatives:
#   letter-start: [A-Za-z] + 1+ alphanumeric  → catches #AI, #GPS (min 2 chars)
#   digit-start:  digits + letter + alphanumeric → catches #10SmallSt, #60thBigBash
_TAG_RE = re.compile(r'(?<!\w)#([A-Za-z][A-Za-z0-9]+|[0-9]+[A-Za-z][A-Za-z0-9]*)')
_TAG_BLOCKLIST = {"heading", "slide", "gid", "vis", "showing", "sthash",
                  "providers", "dashboard", "exec"}

def extract_tags(text: str) -> set:
    tags = set()
    for m in _TAG_RE.findall(text):
        low = m.lower()
        if low in _TAG_BLOCKLIST:
            continue
        if all(c in "0123456789abcdefABCDEF" for c in m) and 6 <= len(m) <= 8:
            continue
        tags.add("#" + m)
    return tags


# ── Config ───────────────────────────────────────────────────────────────

def load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


# ── Thread-safe state ────────────────────────────────────────────────────

_lock  = threading.Lock()
_state: dict = {
    "notes":           [],
    "index":           [],    # client-safe subset (no _ keys)
    "folders":         [],
    "tags":            [],
    "last_sync":       None,  # datetime | None
    "notes_root":      None,  # Path | None (only set when the dir actually exists)
    "configured_root": "",    # raw string from config — may be invalid; shown in Settings
    "index_progress":  {"active": False, "done": 0, "total": 0},
}


# ── Indexer ──────────────────────────────────────────────────────────────

def build_index(notes_root: Path) -> list:
    # Collect eligible files first so we know the total for progress reporting
    html_files = [
        f for f in notes_root.rglob("*.html")
        if len(f.relative_to(notes_root).parts) == 3
        and f.relative_to(notes_root).parts[1] not in _SKIP_FOLDERS
    ]
    total = len(html_files)
    with _lock:
        _state["index_progress"] = {"active": True, "done": 0, "total": total}

    notes = []
    for i, html_file in enumerate(html_files):
        parts  = html_file.relative_to(notes_root).parts
        folder = "/".join(parts[:-1])   # e.g. "iCloud/Notes"

        try:
            raw = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        p = NoteParser()
        p.feed(raw)

        title = p.title.strip() if p.title else ""
        if not title:
            # Fall back to filename — strip leading "YYYY-MM-DD " date prefix
            title = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", html_file.stem).strip()

        # Primary date source: <meta name="modified"> (set by apple-notes-exporter).
        # Format: "D Mon YYYY at H:MM am/pm" e.g. "5 Dec 2019 at 6:28 am".
        # Falls back to file mtime if the tag is absent or unparseable.
        date = None
        if p.modified:
            try:
                date = datetime.strptime(p.modified, "%d %b %Y at %I:%M %p")
            except ValueError:
                pass
        if date is None:
            date = datetime.fromtimestamp(html_file.stat().st_mtime)

        body    = p.body_text()
        snippet = body[:280].strip()

        # Tags in the filename stem are Apple Notes' native tags — authoritative source.
        # Strip the leading "YYYY-MM-DD " date prefix before extracting.
        stem      = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", html_file.stem)
        stem_tags = extract_tags(stem)
        body_tags = extract_tags(title + " " + body)
        all_tags  = stem_tags | body_tags

        notes.append({
            "file":       "/".join(parts),   # e.g. "iCloud/Notes/2026-04-15 My Note.html"
            "folder":     folder,
            "title":      title,
            "date":       date.strftime("%Y-%m-%d"),
            "snippet":    snippet,
            "_search":    (title + " " + body).lower(),
            "_path":      str(html_file),
            "_tags":      all_tags,
            "_stem_tags": stem_tags,          # filename-sourced tags (native Apple Notes tags)
        })

        # Update progress every 25 files to limit lock contention
        if i % 25 == 0:
            with _lock:
                _state["index_progress"]["done"] = i + 1

    notes.sort(key=lambda n: n["date"], reverse=True)
    return notes


def _rebuild(notes_root: Path | None = None) -> None:
    """Re-index notes and swap state atomically. Runs synchronously."""
    if notes_root is None:
        cfg      = load_config()
        root_str = cfg.get("notes_root", "")
        notes_root = Path(root_str) if root_str else None

    if notes_root is None or not notes_root.is_dir():
        with _lock:
            _state["notes_root"]     = notes_root
            _state["index_progress"] = {"active": False, "done": 0, "total": 0}
        return

    # build_index() updates _state["index_progress"]["done"] as it runs
    notes   = build_index(notes_root)
    index   = [{k: v for k, v in n.items() if not k.startswith("_")} for n in notes]
    folders = sorted({n["folder"] for n in notes})

    # Dual-source tag counting:
    #   stem_tag_counts — tags found in filenames (native Apple Notes tags)
    #   all_tag_counts  — tags from both filenames and note body text
    # Show a tag if it appears in ≥1 note via filename (authoritative),
    # or in ≥2 notes via body text (noise filter for body-only tags).
    stem_tag_counts: dict[str, int] = {}
    all_tag_counts:  dict[str, int] = {}
    for n in notes:
        for t in n["_stem_tags"]:
            stem_tag_counts[t] = stem_tag_counts.get(t, 0) + 1
        for t in n["_tags"]:
            all_tag_counts[t] = all_tag_counts.get(t, 0) + 1
    tags = [
        {"tag": t, "count": c}
        for t, c in sorted(all_tag_counts.items(), key=lambda x: (-x[1], x[0].lower()))
        if stem_tag_counts.get(t, 0) >= 1 or c >= 2
    ]

    with _lock:
        _state["notes"]      = notes
        _state["index"]      = index
        _state["folders"]    = folders
        _state["tags"]       = tags
        _state["notes_root"] = notes_root
        # Mark complete AFTER state is fully swapped so clients see consistent data
        _state["index_progress"]["active"] = False
        _state["index_progress"]["done"]   = _state["index_progress"]["total"]

    print(f"  {len(notes)} notes · {len(folders)} folder(s) · {len(tags)} tags.", flush=True)


def _start_rebuild_async(notes_root: Path | None = None) -> None:
    """Start _rebuild() in a background daemon thread. Returns immediately."""
    threading.Thread(target=_rebuild, args=(notes_root,), daemon=True).start()


# ── Settings page ────────────────────────────────────────────────────────

_SETTINGS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Notes — Settings</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", system-ui, sans-serif;
      background: #F2EFE7; color: #1C1C1E;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; padding: 24px;
      -webkit-font-smoothing: antialiased;
    }
    .card {
      background: #fff; border-radius: 14px;
      box-shadow: 0 2px 20px rgba(0,0,0,0.10);
      padding: 36px 40px 32px; max-width: 520px; width: 100%;
    }
    h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.4px; margin-bottom: 6px; }
    p.sub { font-size: 14px; color: #636366; margin-bottom: 28px; line-height: 1.5; }
    p.sub code {
      font-family: "SF Mono", Menlo, monospace; font-size: 12px;
      background: #F2EFE7; padding: 1px 5px; border-radius: 4px;
    }
    label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 7px; }
    .path-row { display: flex; gap: 8px; }
    input[type=text] {
      flex: 1; min-width: 0; padding: 10px 12px; font-size: 14px; font-family: inherit;
      border: 1.5px solid rgba(0,0,0,0.12); border-radius: 8px;
      background: #F7F5EE; color: #1C1C1E; outline: none;
      transition: border-color 0.15s;
    }
    input[type=text]:focus { border-color: #FFCC00; }
    .browse-open-btn {
      flex-shrink: 0; padding: 10px 14px; font-size: 14px; font-family: inherit;
      border: 1.5px solid rgba(0,0,0,0.12); border-radius: 8px;
      background: #F7F5EE; color: #1C1C1E; cursor: pointer;
      transition: border-color 0.15s, background 0.15s; white-space: nowrap;
    }
    .browse-open-btn:hover { border-color: #FFCC00; background: #fff; }
    .hint { font-size: 12px; color: #AEAEB2; margin-top: 7px; line-height: 1.5; }
    .btn {
      margin-top: 24px; width: 100%; padding: 12px;
      background: #FFCC00; border: none; border-radius: 9px;
      font-size: 15px; font-weight: 600; font-family: inherit;
      cursor: pointer; transition: opacity 0.15s;
    }
    .btn:hover { opacity: 0.85; }
    .btn:disabled { opacity: 0.5; cursor: default; }
    .msg { margin-top: 16px; font-size: 14px; text-align: center; min-height: 20px; }
    .msg.ok  { color: #34C759; }
    .msg.err { color: #FF3B30; }

    /* Progress bar */
    .progress-section { display: none; margin-top: 20px; }
    .progress-track {
      background: rgba(0,0,0,0.08); border-radius: 10px;
      height: 8px; overflow: hidden; margin-bottom: 9px;
    }
    .progress-fill {
      height: 100%; background: #FFCC00; border-radius: 10px;
      width: 0%; transition: width 0.25s ease;
    }
    .progress-label { font-size: 12px; color: #636366; text-align: center; }
    /* Indeterminate sweep — shown while scanning (total unknown) */
    @keyframes scan-sweep {
      0%   { transform: translateX(-150%); }
      100% { transform: translateX(550%); }
    }
    .progress-fill.scanning {
      width: 22% !important;
      transition: none;
      animation: scan-sweep 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }

    /* Folder browser overlay */
    .browse-overlay {
      display: none; position: fixed; inset: 0; z-index: 9000;
      background: rgba(0,0,0,0.45);
      align-items: center; justify-content: center;
      backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
    }
    .browse-overlay.open { display: flex; }
    .browse-card {
      background: #fff; border-radius: 14px;
      width: min(580px, 94vw); max-height: 72vh;
      display: flex; flex-direction: column;
      box-shadow: 0 8px 40px rgba(0,0,0,0.22);
      overflow: hidden;
    }
    .browse-hd {
      padding: 14px 18px; display: flex; align-items: center;
      border-bottom: 1px solid rgba(0,0,0,0.07); flex-shrink: 0;
    }
    .browse-hd-title { font-size: 15px; font-weight: 600; flex: 1; }
    .browse-hd-x {
      background: none; border: none; font-size: 20px;
      color: #636366; cursor: pointer; line-height: 1; padding: 0 2px;
    }
    .browse-crumb {
      padding: 7px 18px; font-size: 11px; font-family: "SF Mono", Menlo, monospace;
      color: #636366; background: #F7F5EE;
      border-bottom: 1px solid rgba(0,0,0,0.06); flex-shrink: 0;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      direction: rtl; text-align: left;
    }
    .browse-list { flex: 1; overflow-y: auto; }
    .browse-entry {
      padding: 10px 18px; display: flex; align-items: center; gap: 10px;
      cursor: pointer; font-size: 14px; transition: background 0.1s;
    }
    .browse-entry:hover { background: rgba(0,0,0,0.04); }
    .browse-entry-ico { font-size: 15px; flex-shrink: 0; }
    .browse-entry-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .browse-empty { padding: 24px 18px; font-size: 14px; color: #AEAEB2; text-align: center; }
    .browse-ft {
      padding: 12px 18px; border-top: 1px solid rgba(0,0,0,0.07); flex-shrink: 0;
    }
    .browse-sel {
      width: 100%; padding: 11px; background: #FFCC00;
      border: none; border-radius: 8px;
      font-size: 14px; font-weight: 600; font-family: inherit;
      cursor: pointer; transition: opacity 0.15s;
    }
    .browse-sel:hover { opacity: 0.85; }

    @media (prefers-color-scheme: dark) {
      body { background: #1C1C1E; color: #F2F2F7; }
      .card { background: #2C2C2E; box-shadow: 0 2px 20px rgba(0,0,0,0.4); }
      p.sub, .hint, .progress-label { color: #AEAEB2; }
      p.sub code { background: #3A3A3C; }
      input[type=text] { background: #3A3A3C; border-color: rgba(255,255,255,0.08); color: #F2F2F7; }
      .browse-open-btn { background: #3A3A3C; border-color: rgba(255,255,255,0.08); color: #F2F2F7; }
      .browse-open-btn:hover { background: #48484A; border-color: #FFCC00; }
      label { color: #F2F2F7; }
      .progress-track { background: rgba(255,255,255,0.10); }
      .browse-card { background: #2C2C2E; }
      .browse-hd { border-color: rgba(255,255,255,0.06); }
      .browse-crumb { background: #3A3A3C; border-color: rgba(255,255,255,0.05); color: #AEAEB2; }
      .browse-ft { border-color: rgba(255,255,255,0.06); }
      .browse-entry:hover { background: rgba(255,255,255,0.06); }
      .browse-entry { color: #F2F2F7; }
      .browse-hd-x { color: #AEAEB2; }
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Notes Folder</h1>
    <p class="sub">Choose the folder that contains your exported notes.
    It should hold account subdirectories—for example
    <code>iCloud/</code> and <code>On My Mac/</code>—with Apple Notes folders inside.</p>

    <label for="notesPath">Notes folder path</label>
    <div class="path-row">
      <input type="text" id="notesPath"
             placeholder="/Users/you/Documents/AppleNotes"
             value="CURRENT_PATH">
      <button class="browse-open-btn" id="browseOpenBtn" type="button">Browse…</button>
    </div>
    <p class="hint">Tip: drag the folder from Finder into Terminal and copy the path shown.</p>

    <button class="btn" id="saveBtn">Save &amp; Index Notes</button>
    <div class="msg" id="msg"></div>

    <div class="progress-section" id="progressSection">
      <div class="progress-track">
        <div class="progress-fill" id="progressFill"></div>
      </div>
      <p class="progress-label" id="progressLabel">Indexing…</p>
    </div>
  </div>

  <!-- Folder browser overlay -->
  <div class="browse-overlay" id="browseOverlay">
    <div class="browse-card">
      <div class="browse-hd">
        <span class="browse-hd-title">Choose Notes Folder</span>
        <button class="browse-hd-x" id="browseCancelBtn" title="Cancel">×</button>
      </div>
      <div class="browse-crumb" id="browseCrumb">…</div>
      <div class="browse-list" id="browseList"></div>
      <div class="browse-ft">
        <button class="browse-sel" id="browseSelectBtn">Select This Folder</button>
      </div>
    </div>
  </div>

  <script>
    const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    let currentBrowsePath = "";

    // ── Folder browser ──────────────────────────────────────────────
    async function browseTo(path) {
      const r = await fetch("/api/browse?path=" + encodeURIComponent(path || ""));
      const d = await r.json();
      currentBrowsePath = d.path;
      document.getElementById("browseCrumb").textContent = d.path;

      const list = document.getElementById("browseList");
      list.innerHTML = "";

      // "Go up" row
      if (d.parent) {
        const up = document.createElement("div");
        up.className = "browse-entry";
        up.innerHTML = '<span class="browse-entry-ico">↑</span>' +
                       '<span class="browse-entry-name">↑ &nbsp;Go up</span>';
        up.addEventListener("click", () => browseTo(d.parent));
        list.appendChild(up);
      }

      if (d.entries.length === 0) {
        list.innerHTML += '<div class="browse-empty">No subfolders</div>';
        return;
      }

      for (const e of d.entries) {
        const el = document.createElement("div");
        el.className = "browse-entry";
        el.innerHTML = '<span class="browse-entry-ico">📁</span>' +
                       '<span class="browse-entry-name">' + esc(e.name) + '</span>';
        el.addEventListener("click", () => browseTo(e.path));
        list.appendChild(el);
      }
    }

    document.getElementById("browseOpenBtn").addEventListener("click", async () => {
      const cur = document.getElementById("notesPath").value.trim();
      document.getElementById("browseOverlay").classList.add("open");
      await browseTo(cur || "");
    });
    document.getElementById("browseCancelBtn").addEventListener("click", () => {
      document.getElementById("browseOverlay").classList.remove("open");
    });
    document.getElementById("browseOverlay").addEventListener("click", e => {
      if (e.target === document.getElementById("browseOverlay"))
        document.getElementById("browseOverlay").classList.remove("open");
    });
    document.getElementById("browseSelectBtn").addEventListener("click", () => {
      document.getElementById("notesPath").value = currentBrowsePath;
      document.getElementById("browseOverlay").classList.remove("open");
    });

    // ── Save & index ────────────────────────────────────────────────
    function startProgressPolling() {
      const fill  = document.getElementById("progressFill");
      const label = document.getElementById("progressLabel");
      document.getElementById("progressSection").style.display = "block";

      function poll() {
        fetch("/api/index-status").then(r => r.json()).then(d => {
          if (d.active) {
            if (d.total === 0) {
              // File-scan phase — total unknown; show indeterminate sweep
              fill.classList.add("scanning");
              label.textContent = "Scanning notes folder…";
            } else {
              // Indexing phase — show determinate progress
              fill.classList.remove("scanning");
              const pct = Math.round(d.done / d.total * 100);
              fill.style.width = pct + "%";
              label.textContent = d.done.toLocaleString() + " of " +
                                  d.total.toLocaleString() + " notes indexed…";
            }
            setTimeout(poll, 250);
          } else {
            fill.classList.remove("scanning");
            fill.style.width = "100%";
            label.textContent = "✓ " + d.count.toLocaleString() + " notes indexed.";
            setTimeout(() => { window.location.href = "/"; }, 900);
          }
        }).catch(() => setTimeout(poll, 500));
      }
      poll();
    }

    document.getElementById("saveBtn").addEventListener("click", async () => {
      const path = document.getElementById("notesPath").value.trim();
      const msg  = document.getElementById("msg");
      const btn  = document.getElementById("saveBtn");
      if (!path) { msg.textContent = "Please enter a path."; msg.className = "msg err"; return; }
      msg.textContent = ""; msg.className = "msg";
      btn.disabled = true; btn.textContent = "Saving…";
      try {
        const r = await fetch("/settings", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({notes_root: path})
        });
        const d = await r.json();
        if (d.status === "indexing") {
          btn.textContent = "Indexing…";
          startProgressPolling();
        } else if (d.status === "ok") {
          // Synchronous fallback (shouldn't normally occur)
          window.location.href = "/";
        } else {
          msg.textContent = "Error: " + (d.message || "unknown error");
          msg.className = "msg err";
          btn.disabled = false; btn.textContent = "Save & Index Notes";
        }
      } catch(e) {
        msg.textContent = "Error: " + e.message;
        msg.className = "msg err";
        btn.disabled = false; btn.textContent = "Save & Index Notes";
      }
    });
  </script>
</body>
</html>
"""


# ── Request handler ──────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silent

    def _snap(self):
        """Return a consistent snapshot of _state for this request."""
        with _lock:
            return dict(_state)   # lists replaced atomically — shallow copy is safe

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        qs     = parse_qs(parsed.query)
        state  = self._snap()

        # First-run guard: redirect to Settings until a valid notes folder is set.
        # /api/browse must be allowed through so the Settings page browse button works.
        _SETTINGS_PATHS = {"/settings", "/favicon.ico", "/api/browse"}
        if state["notes_root"] is None and path not in _SETTINGS_PATHS:
            self.send_response(302)
            self.send_header("Location", "/settings")
            self.end_headers()
            return

        # ── Static UI ───────────────────────────────────────────────────
        if path in ("/", "/index.html"):
            self._file(APP_HTML, "text/html; charset=utf-8")

        elif path == "/settings":
            # Prefer the live valid path; fall back to the raw configured string
            # so the user can see and correct a stale/wrong path from config.json.
            current = (str(state["notes_root"]) if state["notes_root"]
                       else state.get("configured_root", ""))
            html    = _SETTINGS_HTML.replace("CURRENT_PATH", current)
            body    = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ── Notes API ───────────────────────────────────────────────────
        elif path == "/api/notes":
            folder = qs.get("folder", [""])[0]
            data   = (
                [n for n in state["index"] if n["folder"] == folder]
                if folder and folder != "__all__"
                else state["index"]
            )
            self._json(data)

        elif path == "/api/search":
            q      = qs.get("q", [""])[0].strip().lower()
            folder = qs.get("folder", [""])[0]
            pool   = (
                [n for n in state["notes"] if n["folder"] == folder]
                if folder and folder != "__all__"
                else state["notes"]
            )
            if len(q) < 2:
                results = [{k: v for k, v in n.items() if not k.startswith("_")} for n in pool]
            else:
                results = [
                    {k: v for k, v in n.items() if not k.startswith("_")}
                    for n in pool if q in n["_search"]
                ]
            self._json(results)

        elif path == "/api/note":
            fname = unquote(qs.get("file", [""])[0])
            if fname and ".." not in fname:
                match = next((n for n in state["notes"] if n["file"] == fname), None)
                if match:
                    self._file(Path(match["_path"]), "text/html; charset=utf-8")
                    return
            self.send_error(404)

        elif path == "/api/folders":
            notes = state["notes"]
            folder_counts: dict[str, int] = {}
            for n in notes:
                folder_counts[n["folder"]] = folder_counts.get(n["folder"], 0) + 1

            groups_map: dict[str, list] = {}
            for fpath in sorted(folder_counts):
                segs  = fpath.split("/")
                group = segs[0]
                name  = "/".join(segs[1:]) if len(segs) > 1 else segs[0]
                is_del = name.lower() in ("recently deleted", "trash", "deleted items")
                groups_map.setdefault(group, []).append({
                    "name": name, "path": fpath,
                    "count": folder_counts[fpath], "deleted": is_del,
                })

            groups = [
                {"label": g, "folders": flds}
                for g, flds in sorted(groups_map.items())
            ]
            self._json({"total": len(notes), "groups": groups})

        elif path == "/api/tags":
            self._json(state["tags"])

        elif path == "/api/sync":
            last = state["last_sync"]
            self._json({
                "last_synced": last.isoformat() if last else None,
                "count":       len(state["notes"]),
            })

        elif path == "/api/index-status":
            with _lock:
                prog  = dict(_state["index_progress"])
                count = len(_state["notes"])
            self._json({**prog, "count": count})

        elif path == "/api/browse":
            # Directory browser used by the settings page file picker.
            # req_path comes from whatever the user has typed in the path field.
            req_path = unquote(qs.get("path", [""])[0]).strip()
            if req_path:
                browse_dir = Path(req_path).expanduser().resolve()
            else:
                # No path typed: start near the current valid root, else home.
                nr = state["notes_root"]
                browse_dir = nr.parent if nr else Path.home()

            # If the path doesn't exist (e.g. stale laptop path), fall back to home
            # so the user can navigate from a known-good starting point.
            if not browse_dir.is_dir():
                browse_dir = Path.home()

            parent = str(browse_dir.parent) if browse_dir != browse_dir.parent else None
            entries = []
            try:
                for entry in sorted(browse_dir.iterdir(),
                                    key=lambda e: e.name.lower()):
                    if entry.name.startswith(".") or not entry.is_dir():
                        continue
                    entries.append({"name": entry.name, "path": str(entry)})
            except PermissionError:
                pass   # return empty list for restricted dirs

            self._json({
                "path":    str(browse_dir),
                "parent":  parent,
                "entries": entries,
            })

        # ── Static file serving ─────────────────────────────────────────
        elif path.startswith("/static/"):
            notes_root = state["notes_root"]
            if notes_root is None:
                self.send_error(503); return
            rel = unquote(path[8:])
            if ".." not in rel:
                fp = notes_root / rel
                if fp.is_file():
                    self._file(fp, MIME.get(fp.suffix.lower(), "application/octet-stream"))
                    return
            self.send_error(404)

        else:
            self.send_error(404)

    def do_POST(self):
        parsed  = urlparse(self.path)
        path    = parsed.path
        length  = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length) if length else b""

        # ── Save settings ───────────────────────────────────────────────
        if path == "/settings":
            try:
                data           = json.loads(payload)
                notes_root_str = data.get("notes_root", "").strip()
                if not notes_root_str:
                    self._json({"status": "error", "message": "Path is required"}); return
                notes_root = Path(notes_root_str).expanduser()
                if not notes_root.is_dir():
                    self._json({"status": "error",
                                "message": f"Directory not found: {notes_root}"}); return
                _CONFIG_FILE.write_text(
                    json.dumps({"notes_root": str(notes_root)}, indent=2)
                )
                # Mark active=True NOW so the client can't see a stale 'done'
                # state between the POST response and the thread actually starting.
                with _lock:
                    _state["index_progress"] = {"active": True, "done": 0, "total": 0}
                _start_rebuild_async(notes_root)
                self._json({"status": "indexing"})
            except Exception as e:
                self._json({"status": "error", "message": str(e)})

        # ── Trigger sync ────────────────────────────────────────────────
        elif path == "/api/sync":
            sync_sh = BASE_DIR / "sync.sh"
            if not sync_sh.exists():
                self._json({"status": "error", "message": "sync.sh not found"}); return
            try:
                subprocess.run(
                    ["bash", str(sync_sh)],
                    timeout=300, check=True,
                    capture_output=True, text=True,
                )
                now = datetime.now()
                with _lock:
                    _state["last_sync"] = now
                    _state["index_progress"] = {"active": True, "done": 0, "total": 0}
                _start_rebuild_async()          # index in background
                self._json({"status": "indexing"})
            except subprocess.TimeoutExpired:
                self._json({"status": "error", "message": "Sync timed out after 5 minutes"})
            except subprocess.CalledProcessError as e:
                self._json({"status": "error",
                            "message": e.stderr.strip() or "sync.sh exited with an error"})
            except Exception as e:
                self._json({"status": "error", "message": str(e)})

        else:
            self.send_error(405)

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
            self.send_error(500); return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Prime state from config immediately so the HTTP server can start serving
    # right away. The browser gets a loading screen while indexing runs async.
    cfg      = load_config()
    root_str = cfg.get("notes_root", "")
    if root_str:
        # Always preserve the raw configured path so the Settings page can show
        # it even when the directory doesn't exist on this machine.
        with _lock:
            _state["configured_root"] = root_str
        notes_root = Path(root_str).expanduser()
        if notes_root.is_dir():
            with _lock:
                _state["notes_root"]     = notes_root
                _state["index_progress"] = {"active": True, "done": 0, "total": 0}
            _start_rebuild_async(notes_root)
            print(f"Indexing notes…", flush=True)
        else:
            print(f"  ⚠  Notes folder not found: {notes_root}", flush=True)
    else:
        print("  No Notes folder configured — open the app to set it up.", flush=True)

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"  → http://127.0.0.1:{PORT}")
    print("    Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

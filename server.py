#!/usr/bin/env python3
"""Notes Viewer — local HTTP server"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from html import unescape as html_unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

BASE_DIR    = Path(__file__).parent
APP_HTML    = BASE_DIR / "app.html"
PORT        = 8765
APP_VERSION = "3.0.0"

_CONFIG_FILE  = BASE_DIR / "config.json"
_SKIP_FOLDERS = set()   # Apple Notes folders excluded entirely from the index

# Folders that are indexed and shown everywhere, but flagged so the UI can
# display them with a visual warning. Notes here are pending permanent deletion
# in Apple Notes (30-day window) — they can still be restored from Apple Notes.
_RECENTLY_DELETED_FOLDERS = {"recently deleted", "trash", "deleted items"}

_NOTES_EXPORT_CANDIDATES = [
    "/usr/local/bin/notes-export",
    "/opt/homebrew/bin/notes-export",
    "/Applications/Apple Notes Exporter.app/Contents/SharedSupport/notes-export",
    str(Path.home() / "bin/notes-export"),
    str(Path.home() / ".local/bin/notes-export"),
]

def _find_notes_export_bin() -> str | None:
    env_bin = os.environ.get("NOTES_EXPORT_BIN", "").strip()
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin
    found = shutil.which("notes-export")
    if found:
        return found
    for c in _NOTES_EXPORT_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

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
    "sync_progress":   {"active": False, "done": 0, "total": 0, "current": "", "error": None},
    "sync_log":        None,   # structured report from the last completed sync
    "index_version":   0,      # bumped on every _rebuild() — clients use it to cache /api/notes
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
        parts            = html_file.relative_to(notes_root).parts
        folder           = "/".join(parts[:-1])   # e.g. "iCloud/Notes"
        recently_deleted = parts[1].lower() in _RECENTLY_DELETED_FOLDERS

        # Stat once — used for file size and mtime fallback.
        try:
            st = html_file.stat()
        except OSError:
            continue
        file_size = st.st_size

        # Attachment folder: {stem} + " (Attachments)" in the same directory.
        att_dir         = html_file.parent / (html_file.stem + " (Attachments)")
        has_attachments = att_dir.is_dir()

        # Read at most _INDEX_READ_MAX bytes. Title and <meta name="modified"> are
        # always within the first ~1 KB; snippet caps at 280 chars; the search
        # corpus caps at _SEARCH_BODY_MAX of body text. Notes larger than the cap
        # are typically multi-MB base64 image dumps with little additional text
        # past the head — reading the rest would waste memory for no benefit.
        try:
            with open(html_file, "rb") as fh:
                raw_bytes = fh.read(_INDEX_READ_MAX)
            raw = raw_bytes.decode("utf-8", errors="ignore")
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
            date = datetime.fromtimestamp(st.st_mtime)

        body         = p.body_text()
        snippet      = body[:280].strip()
        search_body  = body[:_SEARCH_BODY_MAX]    # cap memory; matches usually near top

        # Tags in the filename stem are Apple Notes' native tags — authoritative source.
        # Strip the leading "YYYY-MM-DD " date prefix before extracting.
        stem      = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", html_file.stem)
        stem_tags = extract_tags(stem)
        body_tags = extract_tags(title + " " + search_body)
        all_tags  = stem_tags | body_tags

        notes.append({
            "file":             "/".join(parts),   # e.g. "iCloud/Notes/2026-04-15 My Note.html"
            "folder":           folder,
            "title":            title,
            "date":             date.strftime("%Y-%m-%d"),
            "snippet":          snippet,
            "size":             file_size,          # HTML file size in bytes (includes inline base64 images)
            "has_attachments":  has_attachments,    # True → (Attachments)/ folder exists alongside HTML
            "recently_deleted": recently_deleted,   # True → note is pending deletion in Apple Notes
            "_search":          (title + " " + search_body).lower(),
            "_path":            str(html_file),
            "_tags":            all_tags,
            "_stem_tags":       stem_tags,          # filename-sourced tags (native Apple Notes tags)
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
        _state["notes"]         = notes
        _state["index"]         = index
        _state["folders"]       = folders
        _state["tags"]          = tags
        _state["notes_root"]    = notes_root
        _state["index_version"] = _state.get("index_version", 0) + 1
        # Mark complete AFTER state is fully swapped so clients see consistent data
        _state["index_progress"]["active"] = False
        _state["index_progress"]["done"]   = _state["index_progress"]["total"]

    print(f"  {len(notes)} notes · {len(folders)} folder(s) · {len(tags)} tags.", flush=True)


def _start_rebuild_async(notes_root: Path | None = None) -> None:
    """Start _rebuild() in a background daemon thread. Returns immediately."""
    threading.Thread(target=_rebuild, args=(notes_root,), daemon=True).start()


def _count_notes_for_progress(bin_path: str) -> int:
    """Best-effort total note count for a full-export progress bar.

    Only meaningful for a full export (no watermark): list-notes returns every
    note in the Notes DB, whereas an incremental run re-exports only the changed
    subset — so we never call this when a watermark is present. Any failure
    (no Full Disk Access, unexpected JSON, timeout) returns 0, and the client
    falls back to the indeterminate "actively working" indicator.
    """
    try:
        out = subprocess.run(
            [bin_path, "list-notes", "--format", "json"],
            capture_output=True, text=True, timeout=90,
        ).stdout
        data = json.loads(out)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("notes", "items", "results"):
                if isinstance(data.get(key), list):
                    return len(data[key])
    except Exception:
        pass
    return 0


_DATE_PREFIX_STRIP    = re.compile(r'^\d{4}-\d{2}-\d{2} ')
_HREF_SRC_RE          = re.compile(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
_PROGRESS_COUNTER_RE  = re.compile(r'^\[\d+/\d+\]$')   # exporter progress lines e.g. [3/7]
_INCREMENTAL_TOTAL_RE = re.compile(r'Incremental sync:\s+\d+\s+new/changed\s+of\s+(\d+)\s+total', re.IGNORECASE)
# Emitted by apple-notes-exporter --verbose for notes whose watermark entry has been
# removed from Apple Notes since the last export. Format:
#   Deleted (no longer in Notes): iCloud/Notes/VBC Training.html
# The captured group is the relative path from notes_root — directly usable with
# /api/note/delete. The exporter updates its watermark but does NOT remove the HTML
# file from disk, so these files remain as stale orphans until explicitly removed.
_DELETED_NOTE_RE = re.compile(r'Deleted \(no longer in Notes\):\s+(.+)', re.IGNORECASE)

# Stale-note drift detection thresholds.
# A warning is shown in the Sync Report when the number of indexed HTML files
# exceeds the exporter's reported Apple Notes total by at least this much.
# This indicates notes deleted in Apple Notes still exist on disk as orphaned HTML.
_DRIFT_THRESHOLD_ABS = 10     # minimum absolute stale-note count before warning fires
_DRIFT_THRESHOLD_PCT = 0.02   # minimum percentage drift (2%) before warning fires

# Image file extensions the exporter ALWAYS stores in (Attachments) as raw copies
# of inline base64 content — the HTML uses data: URIs, never path hrefs, so these
# files will never appear in `referenced`. Never delete them.
_IMAGE_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".heic", ".heif",
    ".tiff", ".tif", ".bmp", ".webp", ".svg", ".avif",
})

# ── Tunable thresholds (named so they're discoverable) ──────────────────
# Maximum HTML bytes read by _referenced_attachments() — base64-image-heavy notes
# (multi-MB) are skipped entirely rather than parsed, to avoid expensive reads on
# every sync. The threshold sits well above any realistic plain-text note size.
_MAX_REFERENCED_HTML_SIZE = 10 * 1024 * 1024   # 10 MB

# Consistency gate for orphan-attachment cleanup — abort if fewer than this
# fraction of pre-sync notes are still present on disk after the export.
_GATE_THRESHOLD = 0.75

# Filename-scheme auto-detection threshold — append --add-date-prefix only when
# at least this fraction of existing files use the date prefix.
_PREFIX_DETECT_THRESHOLD = 0.80

# notes-export subprocess wall-clock timeout (seconds).
_EXPORT_TIMEOUT_SEC = 300

# Live sync line buffer caps for the streaming output pane.
_LIVE_LINES_MAX  = 1000   # hard ceiling before trimming
_LIVE_LINES_KEEP = 800    # how many to keep after trim
_LIVE_LINES_TAIL = 200    # last-N returned by GET /api/sync for the live pane

# Indexing-time read cap per HTML file. Title + <meta name="modified"> are always
# within the first ~1 KB; snippet caps at 280 chars; the search corpus is capped
# at _SEARCH_BODY_MAX of the body text. Keeping reads bounded eliminates the
# multi-hundred-MB transient memory spike on indexing libraries that contain
# multi-MB inline-base64 image notes.
_INDEX_READ_MAX  = 64 * 1024   # 64 KB read cap during build_index()
_SEARCH_BODY_MAX = 8 * 1024    # 8 KB cap on body text added to _search

# _wait_for_reindex exit timeout — if the index doesn't complete within this
# window, the wait thread gives up and marks the partial log complete. Prevents
# an indefinite zombie thread when _rebuild() crashes silently.
_REINDEX_WAIT_TIMEOUT_SEC = 600   # 10 minutes


def _fmt_size(n: int) -> str:
    """Human-readable byte size for log lines (e.g. 1.4 MB, 812 KB)."""
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _emit_sync_line(line: str) -> None:
    """Append one line to the live sync output buffer (thread-safe, capped).

    Used by both the exporter stderr loop and the cleanup phase so the live
    output pane and the final scrollable report show one continuous log of
    the whole sync run — export, attachment cleanup, then re-index.
    """
    with _lock:
        sp = _state.get("sync_progress")
        if not isinstance(sp, dict):
            return
        sp["current"] = line[:120]
        lines = sp.get("lines")
        if lines is not None:
            lines.append(line)
            if len(lines) > 1000:
                del lines[:-800]


def _referenced_attachments(html_path: Path, att_dir: Path) -> "set[str] | None":
    """Return the set of filenames inside att_dir that the note HTML references.

    Parses href/src attributes in the exported HTML and resolves them relative
    to the HTML file's directory. Only names whose resolved parent equals att_dir
    are included. Returns None when the file is too large to read safely (caller
    should leave the folder untouched). Never raises.
    """
    try:
        if html_path.stat().st_size > _MAX_REFERENCED_HTML_SIZE:
            return None   # base64-image-heavy notes; skip rather than read
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    referenced: set[str] = set()
    att_abs  = att_dir.resolve()
    html_dir = html_path.parent
    for m in _HREF_SRC_RE.finditer(text):
        raw = m.group(1)
        if not raw or raw.startswith(("data:", "http:", "https:", "#")):
            continue
        # Try three forms: raw value, URL-decoded, HTML-entity-decoded.
        # The exporter encodes & as &amp; in attribute values, so a note
        # titled "Mum & Dad" has attachment paths like
        # "Mum &amp; Dad (Attachments)/file.png" in the HTML.
        # unquote() handles %20 etc; html_unescape() handles &amp; → &.
        for candidate in {raw, unquote(raw),
                          html_unescape(raw), html_unescape(unquote(raw))}:
            try:
                p = (html_dir / candidate).resolve()
                if p.parent == att_abs:
                    referenced.add(p.name)
                    break
            except Exception:
                pass
    return referenced


def _prune_orphan_attachments(notes_root: Path, pre_sync_count: int = 0) -> dict:
    """Delete attachment files left behind when a note's attachments change.

    notes-export is additive: editing a note to swap or remove an attachment
    re-exports the HTML but leaves the old file in the note's
    "(Attachments)/" folder. This function finds those orphans and removes them.

    Detection strategy — parse the re-exported HTML, not the watermark:
    The watermark's `attachmentPaths` field is NOT cleared when an attachment
    is removed from a note; it accumulates paths across exports. Trusting it
    would cause us to keep files the note no longer references. Instead, we
    scan every "(Attachments)/" directory on disk, find its note's HTML,
    and delete any file the HTML does not reference. The HTML is the definitive
    source of truth for what the note currently contains.

    Fail-safe by design:
      - watermark missing/unreadable              → consistency gate fails → no-op
      - no corresponding HTML on disk             → skip that folder (note deleted
                                                    from Apple Notes; conservative)
      - HTML file > 10 MB (large base64 images)  → skip that folder (too slow)
      - only regular files directly inside a
        "* (Attachments)" folder are ever
        deleted; note HTML, sibling folders and
        nested directories are never touched

    Returns a dict:
      {files_removed, bytes_freed, dirs_removed,
       items: [{note, file, size}], skipped, skip_reason}
    Never raises.
    """
    result: dict = {
        "files_removed": 0,
        "bytes_freed":   0,
        "dirs_removed":  0,
        "items":         [],   # [{note: str, file: str, size: int}, ...]
        "skipped":       False,
        "skip_reason":   None,
    }

    # Watermark is used ONLY for the consistency gate — not for per-file detection.
    wm = notes_root / "AppleNotesExportSyncWatermark.json"
    try:
        entries = json.loads(wm.read_text(encoding="utf-8")).get("notes", {})
    except Exception:
        return result

    # Consistency gate: if the export folder is grossly out of sync with what was
    # on disk before this sync (interrupted export, cloud-sync tool like Syncthing/
    # Dropbox/iCloud propagating deletes into the folder), do NOT run any cleanup.
    #
    # Denominator: pre_sync_count (notes indexed immediately before this export ran).
    # This is more accurate than len(entries) because the watermark is cumulative —
    # it retains an entry for every note ever exported, including those deleted from
    # Apple Notes years ago (exportedPath stays set; nothing is ever removed). Using
    # len(entries) as the denominator grows over time and eventually fires falsely on
    # healthy folders with accumulated deletions. pre_sync_count reflects only what
    # was actually on disk before the sync, so the gate remains stable regardless of
    # watermark history. Falls back to len(entries) on first-ever run (pre_sync_count=0).
    present = 0
    for entry in entries.values():
        ep = entry.get("exportedPath", "") or ""
        if ep.endswith(".html") and (notes_root / ep).is_file():
            present += 1
    gate_denom = pre_sync_count if pre_sync_count > 0 else len(entries)
    if gate_denom and present < _GATE_THRESHOLD * gate_denom:
        reason = (
            f"Attachment cleanup skipped — export folder inconsistent "
            f"({present} of {gate_denom} notes on disk). "
            f"Folder may be in a cloud-sync share; see README.")
        result["skipped"]     = True
        result["skip_reason"] = reason
        _emit_sync_line("── Attachment cleanup ──")
        _emit_sync_line(f"⚠ {reason}")
        return result

    # Scan every "(Attachments)" directory on disk. For each one, parse the
    # corresponding note HTML to find which files it actually references.
    # Anything not referenced in the HTML is an orphan and can be safely removed.
    _emit_sync_line("── Attachment cleanup ──")
    _emit_sync_line("Scanning (Attachments) folders for orphaned files…")
    folders_scanned = 0
    suffix = " (Attachments)"
    for att_dir in notes_root.rglob("* (Attachments)"):
        if not att_dir.is_dir():
            continue
        try:
            stem      = att_dir.name[:-len(suffix)]
            html_path = att_dir.parent / (stem + ".html")
            if not html_path.is_file():
                # The note was deleted from Apple Notes; the HTML is gone but
                # the folder remains. Leave it alone — the note may still exist
                # in Apple Notes and a future sync might recreate the HTML.
                continue

            referenced = _referenced_attachments(html_path, att_dir)
            if referenced is None:
                continue   # file too large to read; leave folder untouched

            # Guard 1: if the HTML has zero path-references into this folder,
            # skip it entirely. Either all attachments are base64-embedded (no
            # files to clean up) or the HTML is the wrong match for this folder
            # (a stale copy from before the note was renamed). Either way, nothing
            # safe to delete.
            if not referenced:
                continue

            folders_scanned += 1
            note_title = _DATE_PREFIX_STRIP.sub("", stem)
            html_mtime = html_path.stat().st_mtime

            for child in att_dir.iterdir():
                if not child.is_file() or child.name in referenced:
                    continue

                # Guard 2: never delete image files. The exporter always writes
                # raw image copies to (Attachments) even when it embeds them as
                # base64 data: URIs in the HTML. They appear unreferenced but
                # are perfectly current.
                if child.suffix.lower() in _IMAGE_EXTS:
                    continue

                # Guard 3: if this file is newer than the HTML, the HTML was
                # written before the file existed — it can't reference it. The
                # HTML is stale (e.g. a pre-rename copy) and we must not trust
                # it as the authoritative reference list for newer files.
                try:
                    if child.stat().st_mtime > html_mtime:
                        continue
                except Exception:
                    continue

                try:
                    sz = child.stat().st_size
                    child.unlink()
                    result["files_removed"] += 1
                    result["bytes_freed"]   += sz
                    result["items"].append({
                        "note": note_title,
                        "file": child.name,
                        "size": sz,
                    })
                    _emit_sync_line(
                        f"  ✗ orphan removed: {note_title} / "
                        f"{child.name} ({_fmt_size(sz)})")
                except Exception as e:
                    _emit_sync_line(
                        f"  ! could not remove {child.name}: {e}")

            # Remove the folder if it is now empty. The exporter creates
            # "(Attachments)" directories even for notes that have no
            # attachments, and it touches them on every incremental run —
            # which makes them show "Today" in Finder even when unchanged.
            # Removing empty ones keeps the folder tree clean; the exporter
            # will recreate them if the note is re-synced with attachments.
            try:
                if not any(att_dir.iterdir()):
                    att_dir.rmdir()
                    result["dirs_removed"] += 1
                    _emit_sync_line(
                        f"  ✗ empty folder removed: {att_dir.name}")
            except Exception:
                pass

        except Exception:
            continue

    # Cleanup summary — always logged so the user can see it ran.
    fr, bf, dr = (result["files_removed"],
                  result["bytes_freed"],
                  result["dirs_removed"])
    _emit_sync_line(
        f"Scanned {folders_scanned} folder"
        f"{'s' if folders_scanned != 1 else ''}.")
    if fr or dr:
        parts = []
        if fr:
            parts.append(f"{fr} orphan file{'s' if fr != 1 else ''} "
                         f"removed ({_fmt_size(bf)} freed)")
        if dr:
            parts.append(f"{dr} empty folder{'s' if dr != 1 else ''} removed")
        _emit_sync_line("✓ Cleanup: " + " · ".join(parts))
    else:
        _emit_sync_line("✓ Cleanup: nothing to remove — already clean.")
    return result


_DATE_PREFIX_RE = re.compile(r"(?:^|/)\d{4}-\d{2}-\d{2} ")


def _detect_stale_html_files(notes_root: Path) -> list[dict]:
    """List HTML files on disk that aren't present in the current watermark.

    Only meaningful after a `--reset-sync` run: the watermark was wiped and
    rebuilt from scratch, so it now contains entries only for notes that
    currently exist in Apple Notes (including Recently Deleted). Any HTML file
    on disk at depth 3 whose path is NOT in the watermark's exportedPath set
    is stale — either:
      (a) the note was permanently deleted from Apple Notes since the last
          export and its HTML survived, OR
      (b) the note moved to a different folder inside Apple Notes (e.g. into
          Recently Deleted), the exporter wrote the new file at the new path,
          and the old file at the old path was left behind.

    Returned items each carry the relative path, the displayed title (with
    date prefix stripped), and the size — used by the Sync Report UI to render
    a removable list.

    For non-reset incremental runs this MUST NOT be called — the watermark is
    cumulative and will contain entries for deleted notes whose files do exist,
    so on-disk files would be incorrectly flagged as stale.
    """
    wm_path = notes_root / "AppleNotesExportSyncWatermark.json"
    if not wm_path.is_file():
        return []
    try:
        wm      = json.loads(wm_path.read_text(encoding="utf-8"))
        entries = wm.get("notes", {})
        valid   = {(e.get("exportedPath") or "") for e in entries.values()
                   if (e.get("exportedPath") or "").endswith(".html")}
    except Exception:
        return []

    stale: list[dict] = []
    try:
        for f in notes_root.rglob("*.html"):
            rel = f.relative_to(notes_root)
            if len(rel.parts) != 3:
                continue
            rel_str = "/".join(rel.parts)
            if rel_str in valid:
                continue
            try:
                size = f.stat().st_size
            except Exception:
                size = 0
            title = _DATE_PREFIX_STRIP.sub("", rel.stem)
            stale.append({"path": rel_str, "title": title, "size": size})
    except Exception:
        pass
    stale.sort(key=lambda s: s["path"].lower())
    return stale


def _detect_export_prefix_args(notes_root: Path) -> list[str]:
    """Return exporter args so Sync MATCHES the folder's existing filename scheme.

    notes-export defaults to no date prefix; `--add-date-prefix` writes
    `YYYY-MM-DD Title.html`. The incremental manifest keys on the exported path,
    so running Sync under a *different* scheme than the existing files makes the
    exporter treat every note as new and silently duplicates the whole library.

    We detect the existing scheme — preferring the watermark's recorded
    `exportedPath`s, falling back to a scan of on-disk note files — and return
    `["--add-date-prefix", "--date-format", "iso"]` when ≥ 80% are date-prefixed,
    else `[]` (the no-prefix default). An empty/unknown folder → no prefix.
    """
    paths: list[str] = []
    wm = notes_root / "AppleNotesExportSyncWatermark.json"
    try:
        entries = json.loads(wm.read_text(encoding="utf-8")).get("notes", {})
        paths = [e.get("exportedPath", "") for e in entries.values()
                 if (e.get("exportedPath", "") or "").endswith(".html")]
    except Exception:
        paths = []
    if not paths:
        try:
            for i, f in enumerate(notes_root.rglob("*.html")):
                if len(f.relative_to(notes_root).parts) == 3:
                    paths.append(f.name)
                if i > 600:
                    break
        except Exception:
            paths = []
    if not paths:
        return []
    prefixed = sum(1 for p in paths if _DATE_PREFIX_RE.search("/" + p))
    return ["--add-date-prefix", "--date-format", "iso"] \
        if prefixed >= _PREFIX_DETECT_THRESHOLD * len(paths) else []


def _run_export_async(notes_root: Path, bin_path: str,
                      reset_sync: bool = False) -> None:
    """Run notes-export in a background thread, streaming progress into _state.

    Builds a structured sync_log dict throughout — covering export timing,
    all exporter stderr output, orphan cleanup detail, and re-index results —
    and stores it in _state["sync_log"] once the full sync + re-index completes.
    The log is available via GET /api/sync-log and powers the Sync Report modal.

    reset_sync=True passes `--reset-sync` to the exporter, which deletes the
    watermark before exporting. Every note is then treated as new and re-exported
    to its current location in Apple Notes. This is the only reliable way to
    correctly place notes that have moved to Recently Deleted since the last
    full export — the incremental exporter cannot detect Apple-Notes-internal
    folder moves because `modificationDate` does not change for them.
    """
    def run():
        t0 = time.monotonic()
        log: dict = {
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
            "type":       None,   # "full" | "incremental"
            "reset_sync": reset_sync,   # True when user clicked Force Full Re-export
            "scheme":     None,   # "date_prefix" | "no_prefix"
            "export": {
                "duration_s":    0,
                "stderr_lines":  [],   # last ≤500 lines for the UI
                "stderr_total":  0,    # all lines (may exceed capped list)
                "exit_code":     None,
                "error":         None,
                "exporter_total": None,  # live note count from "N new/changed of M total"
                "deleted_notes": [],    # paths from "Deleted (no longer in Notes):" lines
            },
            "cleanup": {
                "files_removed": 0, "bytes_freed": 0, "dirs_removed": 0,
                "items": [], "skipped": False, "skip_reason": None,
            },
            "reindex": {"notes_indexed": 0, "duration_s": 0},
            "stale_files": [],   # populated after reset_sync runs only
            "total_duration_s": 0,
        }

        # ── Phase 1: full-export total (for % bar) ────────────────────
        # reset_sync forces a full export regardless of whether the watermark exists,
        # because --reset-sync deletes it before exporting.
        watermark = notes_root / "AppleNotesExportSyncWatermark.json"
        is_full   = reset_sync or not watermark.exists()
        log["type"] = "full" if is_full else "incremental"
        if is_full:
            total = _count_notes_for_progress(bin_path)
            if total > 0:
                with _lock:
                    _state["sync_progress"]["total"] = total

        # Capture pre-sync note count for the consistency gate in
        # _prune_orphan_attachments. Must be read before the export runs.
        with _lock:
            pre_sync_count = len(_state["notes"])

        # ── Phase 2: detect filename scheme ───────────────────────────
        prefix_args = _detect_export_prefix_args(notes_root)
        log["scheme"] = "date_prefix" if prefix_args else "no_prefix"
        if prefix_args:
            with _lock:
                _state["sync_progress"]["current"] = (
                    "Existing notes use a date prefix — matching scheme…")

        # ── Header lines into the live log ───────────────────────────
        # Build a readable timestamp matching the app's "D Mon YYYY at H:MM am/pm"
        # style, then emit context lines so the terminal log is self-describing.
        _now  = datetime.now()
        _h12  = _now.hour % 12 or 12
        _ampm = "am" if _now.hour < 12 else "pm"
        _mon  = ["Jan","Feb","Mar","Apr","May","Jun",
                 "Jul","Aug","Sep","Oct","Nov","Dec"][_now.month - 1]
        _ts   = f"{_now.day} {_mon} {_now.year} at {_h12}:{_now.minute:02d} {_ampm}"
        if reset_sync:
            _type_label = "Forced full re-export (--reset-sync)"
        elif is_full:
            _type_label = "Full export (no watermark)"
        else:
            _type_label = "Incremental sync"
        _scheme_label = ("Date-prefixed filenames (YYYY-MM-DD)"
                         if prefix_args else "No date prefix")
        _emit_sync_line(f"── Sync started {_ts} ──")
        _emit_sync_line(f"Type: {_type_label}  ·  Scheme: {_scheme_label}")
        if reset_sync:
            _emit_sync_line(
                "⟲ Watermark will be wiped — every note will be re-exported "
                "to its current location in Apple Notes.")
        _emit_sync_line("── Exporter output ──")
        _emit_sync_line("  (✓ = note exported  ·  [N/M] = exporter progress counter: N of M notes done)")

        # ── Phase 3: run the exporter ─────────────────────────────────
        # --incremental is always passed; --reset-sync deletes the watermark first
        # when present, so the incremental run becomes a full re-export.
        cmd = [bin_path, "export",
               "--format", "html",
               "--incremental"]
        if reset_sync:
            cmd.append("--reset-sync")
        cmd.extend(["--verbose", *prefix_args,
                    "--output", str(notes_root)])

        t_export = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            done = 0
            stderr_lines: list[str] = []
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                done += 1
                stderr_lines.append(line)
                # Capture live Apple Notes total from incremental count line
                # e.g. "Incremental sync: 9 new/changed of 1688 total"
                _m = _INCREMENTAL_TOTAL_RE.search(line)
                if _m:
                    log["export"]["exporter_total"] = int(_m.group(1))

                # Capture stale notes the exporter identified as deleted from Apple Notes.
                # e.g. "Deleted (no longer in Notes): iCloud/Notes/VBC Training.html"
                # The exporter updates its watermark for these but leaves the HTML on disk.
                _d = _DELETED_NOTE_RE.search(line)
                if _d:
                    deleted_path = _d.group(1).strip()
                    if deleted_path and deleted_path not in log["export"]["deleted_notes"]:
                        log["export"]["deleted_notes"].append(deleted_path)
                with _lock:
                    _state["sync_progress"]["done"]    = done
                    _state["sync_progress"]["current"] = line[:120]
                    sp_lines = _state["sync_progress"].get("lines")
                    if sp_lines is not None:
                        if _PROGRESS_COUNTER_RE.match(line) and sp_lines:
                            # Merge "[N/M]" onto the preceding line so it reads
                            # "✓ Exported: Title  [N/M]" rather than a bare
                            # counter on its own line. Skip duplicate counters
                            # (the exporter sometimes emits the same one twice).
                            if not sp_lines[-1].endswith(line):
                                sp_lines[-1] = sp_lines[-1] + "  " + line
                        else:
                            sp_lines.append(line)
                        # Keep most recent N lines; trim if needed
                        if len(sp_lines) > _LIVE_LINES_MAX:
                            del sp_lines[:-_LIVE_LINES_KEEP]
            proc.wait(timeout=_EXPORT_TIMEOUT_SEC)
            log["export"]["duration_s"]   = round(time.monotonic() - t_export)
            log["export"]["stderr_total"] = done
            log["export"]["stderr_lines"] = stderr_lines[-500:]  # cap for UI
            log["export"]["exit_code"]    = proc.returncode

            # notes-export exits non-zero when there is nothing to do
            # ("All notes are up to date, nothing to export.") — that is a
            # successful no-op, not a failure. Recognise the benign messages
            # so an unchanged library does not show "Sync failed".
            joined = "\n".join(stderr_lines).lower()
            benign_noop = (
                "nothing to export"          in joined or
                "all notes are up to date"   in joined or
                "no notes to export"         in joined or
                "no changes"                 in joined
            )
            if proc.returncode != 0 and not benign_noop:
                err = f"Export failed (exit {proc.returncode})"
                log["export"]["error"]  = err
                log["total_duration_s"] = round(time.monotonic() - t0)
                with _lock:
                    _state["sync_progress"].update({"active": False, "error": err})
                    _state["sync_log"] = log
                return
            if benign_noop:
                # Normalise so the report shows success, not a scary exit code
                log["export"]["exit_code"] = 0
        except subprocess.TimeoutExpired:
            try: proc.kill()
            except Exception: pass
            err = f"Export timed out after {_EXPORT_TIMEOUT_SEC // 60} minutes"
            log["export"]["error"]      = err
            log["export"]["duration_s"] = round(time.monotonic() - t_export)
            log["total_duration_s"]     = round(time.monotonic() - t0)
            with _lock:
                _state["sync_progress"].update({"active": False, "error": err})
                _state["sync_log"] = log
            return
        except Exception as e:
            log["export"]["error"]      = str(e)
            log["export"]["duration_s"] = round(time.monotonic() - t_export)
            log["total_duration_s"]     = round(time.monotonic() - t0)
            with _lock:
                _state["sync_progress"].update({"active": False, "error": str(e)})
                _state["sync_log"] = log
            return

        # ── Phase 3b: stale-file detection (reset_sync only) ──────────
        # The fresh watermark from --reset-sync only contains entries for notes
        # currently in Apple Notes. Any depth-3 HTML on disk that isn't in the
        # watermark is an orphan: either a permanently-deleted note's surviving
        # HTML, or the old copy of a note that moved between Apple Notes folders
        # (e.g. into Recently Deleted) leaving the original behind.
        if reset_sync:
            try:
                _emit_sync_line("── Stale file detection (post --reset-sync) ──")
                stale = _detect_stale_html_files(notes_root)
                log["stale_files"] = stale
                if stale:
                    _emit_sync_line(
                        f"⚠ {len(stale)} stale HTML file"
                        f"{'s' if len(stale) != 1 else ''} on disk "
                        f"(not in fresh watermark) — listed in Sync Report.")
                else:
                    _emit_sync_line("✓ No stale HTML files — folder matches Apple Notes exactly.")
            except Exception as e:
                _emit_sync_line(f"! Stale-file scan failed: {e}")

        # ── Phase 4: orphan attachment cleanup ────────────────────────
        try:
            with _lock:
                _state["sync_progress"]["current"] = "Cleaning up replaced attachments…"
            cleanup = _prune_orphan_attachments(notes_root,
                                                pre_sync_count=pre_sync_count)
            log["cleanup"] = cleanup
            if cleanup.get("skipped"):
                pass  # status message already set inside _prune_orphan_attachments
            elif cleanup["files_removed"] > 0:
                n_rm = cleanup["files_removed"]
                n_by = cleanup["bytes_freed"]
                msg  = (f"Removed {n_rm} orphaned attachment"
                        f"{'s' if n_rm != 1 else ''} ({n_by // 1024} KB freed)")
                with _lock:
                    _state["sync_progress"]["current"] = msg
            else:
                with _lock:
                    _state["sync_progress"]["current"] = "No orphaned attachments"
        except Exception:
            pass

        # ── Phase 5: kick off re-index ────────────────────────────────
        t_reindex = time.monotonic()
        now = datetime.now()
        with _lock:
            _state["last_sync"]               = now
            _state["sync_progress"]["active"] = False
            _state["index_progress"]          = {"active": True, "done": 0, "total": 0}

        # Capture the FULL combined log — exporter stderr + cleanup actions in
        # one continuous stream — so the report's scrollable pane reads like a
        # terminal window of the whole run, not just the exporter output.
        with _lock:
            full = list(_state["sync_progress"].get("lines", []))
        log["full_log"] = full

        # Write a PARTIAL log immediately so the client always has export + cleanup
        # data even if it polls before _wait_for_reindex has written the final log.
        # log_complete=False tells the client to keep polling until the full log
        # (with real note count and total duration) is available.
        log["log_complete"]     = False
        log["total_duration_s"] = round(time.monotonic() - t0)
        with _lock:
            _state["sync_log"] = dict(log)

        _start_rebuild_async()

        # Finalise the log once indexing completes — updates reindex stats and
        # sets log_complete=True so the client can render the complete report.
        # A wall-clock timeout (_REINDEX_WAIT_TIMEOUT_SEC) prevents an indefinite
        # zombie thread if _rebuild() crashes silently and never sets active=False.
        def _wait_for_reindex():
            deadline = time.monotonic() + _REINDEX_WAIT_TIMEOUT_SEC
            while True:
                time.sleep(0.2)
                with _lock:
                    ip = dict(_state["index_progress"])
                timed_out = time.monotonic() > deadline
                if not ip.get("active", False) or timed_out:
                    with _lock:
                        note_count = len(_state["notes"])
                    log["reindex"]["notes_indexed"] = note_count
                    log["reindex"]["duration_s"]    = round(time.monotonic() - t_reindex)
                    log["total_duration_s"]         = round(time.monotonic() - t0)
                    if timed_out:
                        log["reindex"]["error"] = (
                            f"Re-index wait timed out after "
                            f"{_REINDEX_WAIT_TIMEOUT_SEC // 60} minutes")

                    # ── Drift detection ───────────────────────────────────
                    # If indexed count exceeds the exporter's live Apple Notes
                    # total, deleted notes have left orphaned HTML on disk.
                    # Only fires for incremental syncs where the count line was
                    # captured — benign no-ops and full exports are excluded.
                    exporter_total = log["export"].get("exporter_total")
                    if exporter_total and exporter_total > 0:
                        drift = note_count - exporter_total
                        threshold = max(_DRIFT_THRESHOLD_ABS,
                                        int(exporter_total * _DRIFT_THRESHOLD_PCT))
                        log["drift"] = {
                            "detected":       drift >= threshold,
                            "stale_count":    max(drift, 0),
                            "indexed":        note_count,
                            "exporter_total": exporter_total,
                        }

                    log["log_complete"] = True
                    with _lock:
                        _state["sync_log"] = log
                    break
        threading.Thread(target=_wait_for_reindex, daemon=True).start()

    threading.Thread(target=run, daemon=True).start()


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
    .btn-row { display: flex; gap: 10px; margin-top: 24px; }
    .btn {
      flex: 1.5; padding: 12px;
      background: #FFCC00; border: none; border-radius: 9px;
      font-size: 15px; font-weight: 600; font-family: inherit;
      cursor: pointer; transition: opacity 0.15s;
    }
    .btn:hover { opacity: 0.85; }
    .btn:disabled { opacity: 0.5; cursor: default; }
    .btn-back {
      flex: 1; padding: 12px;
      background: none; border: 1.5px solid rgba(0,0,0,0.12); border-radius: 9px;
      font-size: 15px; font-weight: 600; font-family: inherit;
      color: #636366; cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
    }
    .btn-back:hover { border-color: #636366; color: #1C1C1E; }
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
      .btn-back { border-color: rgba(255,255,255,0.12); color: #AEAEB2; }
      .btn-back:hover { border-color: #AEAEB2; color: #F2F2F7; }
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
             placeholder="PLACEHOLDER_PATH"
             value="CURRENT_PATH">
      <button class="browse-open-btn" id="browseOpenBtn" type="button">Browse…</button>
    </div>
    <p class="hint">PATH_TIP_TEXT</p>

    <div class="btn-row">
      BACK_BTN_HTML
      <button class="btn" id="saveBtn">Save &amp; Index Notes</button>
    </div>
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
        const empty = document.createElement("div");
        empty.className = "browse-empty";
        empty.textContent = "No subfolders";
        list.appendChild(empty);
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
            if sys.platform == "win32":
                placeholder = r"C:\Users\you\Documents\AppleNotes"
                tip = r"Tip: copy the path from Explorer's address bar, e.g. C:\Users\You\Documents\AppleNotes"
            else:
                placeholder = "/Users/you/Documents/AppleNotes"
                tip = "Tip: drag the folder from Finder into Terminal and copy the path shown."
            back_btn = (
                '<button class="btn-back" onclick="window.location.href=\'/'
                '\'">&#8592; Back</button>'
                if current else ""
            )
            html = (_SETTINGS_HTML
                    .replace("CURRENT_PATH", current)
                    .replace("PLACEHOLDER_PATH", placeholder)
                    .replace("PATH_TIP_TEXT", tip)
                    .replace("BACK_BTN_HTML", back_btn))
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
            with _lock:
                sync_prog  = dict(_state["sync_progress"])
                live_lines = list(_state["sync_progress"].get("lines", [])[-_LIVE_LINES_TAIL:])
            self._json({
                "last_synced":   last.isoformat() if last else None,
                "count":         len(state["notes"]),
                "sync_progress": sync_prog,
                "live_lines":    live_lines,
            })

        elif path == "/api/sync-log":
            with _lock:
                log = _state.get("sync_log")
            if log:
                self._json(log)
            else:
                self._json({"available": False})

        elif path == "/api/index-status":
            with _lock:
                prog          = dict(_state["index_progress"])
                count         = len(_state["notes"])
                index_version = _state.get("index_version", 0)
            self._json({
                **prog,
                "count":         count,
                "version":       APP_VERSION,
                "index_version": index_version,   # bumped per _rebuild() — client cache key
            })

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
            try:
                root_abs = notes_root.resolve()
                fp = (notes_root / rel).resolve()
                fp.relative_to(root_abs)
            except Exception:
                self.send_error(404); return
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
            if sys.platform == "win32":
                self._json({
                    "status": "error",
                    "message": (
                        "Sync is not available on Windows. "
                        "Export your notes on your Mac using apple-notes-exporter, "
                        "then copy the updated export folder to this machine."
                    ),
                })
                return

            # Parse optional payload: {"reset_sync": true} → forced full re-export.
            # No payload (or {}) → normal incremental sync.
            reset_sync = False
            try:
                if payload:
                    data       = json.loads(payload)
                    reset_sync = bool(data.get("reset_sync", False))
            except Exception:
                pass   # invalid JSON → treat as plain sync, don't fail

            # Pre-flight checks before the atomic claim — failures should not flip
            # the active flag.
            notes_root = _state.get("notes_root")
            if not notes_root:
                self._json({"status": "error",
                            "message": "Notes folder not configured. Open Settings first."})
                return

            bin_path = _find_notes_export_bin()
            if not bin_path:
                self._json({
                    "status": "error",
                    "message": (
                        "notes-export binary not found.\n"
                        "  Download from https://github.com/kzaremski/apple-notes-exporter/releases\n"
                        "  Place in /usr/local/bin/ or set: export NOTES_EXPORT_BIN=/path/to/notes-export"
                    ),
                })
                return

            # Atomic claim: check-then-set inside one lock window so two
            # near-simultaneous POSTs can't both start a sync.
            with _lock:
                if _state["sync_progress"].get("active", False):
                    self._json({"status": "syncing"})
                    return
                _state["sync_progress"] = {
                    "active": True, "done": 0, "total": 0,
                    "current": "Starting…", "error": None,
                    "lines": [],   # accumulated stderr lines for the live modal view
                }
            _run_export_async(notes_root, bin_path, reset_sync=reset_sync)
            self._json({"status": "syncing", "reset_sync": reset_sync})

        # ── Delete a note HTML file from the export folder ─────────────
        elif path == "/api/note/delete":
            try:
                data = json.loads(payload) if payload else {}
                rel  = data.get("file", "").strip()
                if not rel:
                    self._json({"ok": False, "error": "Missing file parameter"}); return

                with _lock:
                    notes_root = _state.get("notes_root")
                if not notes_root:
                    self._json({"ok": False, "error": "Notes folder not configured"}); return

                # ── Safety guards ────────────────────────────────────────
                # 1. Resolve and confirm path stays inside notes_root
                try:
                    target   = (notes_root / rel).resolve()
                    root_abs = notes_root.resolve()
                except Exception:
                    self._json({"ok": False, "error": "Invalid path"}); return

                if not str(target).startswith(str(root_abs) + os.sep):
                    self._json({"ok": False, "error": "Path outside notes folder"}); return

                # 2. Must be a depth-3 note file (Account/Folder/Note.html)
                rel_parts = Path(rel).parts
                if len(rel_parts) != 3:
                    self._json({"ok": False,
                                "error": "Only note HTML files at depth 3 can be deleted"}); return

                # 3. Must be an HTML file
                if target.suffix.lower() != ".html":
                    self._json({"ok": False, "error": "Only .html files can be deleted"}); return

                # 4. Must exist
                if not target.is_file():
                    self._json({"ok": False, "error": "File not found on disk"}); return

                # ── Delete HTML file ─────────────────────────────────────
                target.unlink()

                # ── Remove watermark entry so next incremental sync ───────
                # re-exports this note if it still exists in Apple Notes.
                #
                # The incremental exporter decides what to skip by comparing
                # each note's modificationDate in Apple Notes against the
                # watermark. If the HTML is gone but the watermark entry
                # remains, the exporter sees the note as "already exported,
                # unchanged" and never rewrites the file — the note stays
                # missing from the viewer permanently even though it still
                # exists in Apple Notes.  Removing the entry makes the next
                # sync treat the note as brand-new and re-export it.
                #
                # For notes that are genuinely gone from Apple Notes (e.g.
                # removed via the Sync Report "Deleted from Apple Notes" card),
                # removing the entry is harmless: the exporter will look up the
                # note by UUID, find it absent, and simply skip it again.
                wm_path = notes_root / "AppleNotesExportSyncWatermark.json"
                try:
                    if wm_path.is_file():
                        wm      = json.loads(wm_path.read_text(encoding="utf-8"))
                        entries = wm.get("notes", {})
                        # exportedPath always uses forward slashes in the watermark
                        rel_fwd    = rel.replace(os.sep, "/")
                        stale_keys = [k for k, e in entries.items()
                                      if (e.get("exportedPath") or "") == rel_fwd]
                        if stale_keys:
                            for k in stale_keys:
                                del entries[k]
                            wm_path.write_text(
                                json.dumps(wm, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                except Exception:
                    pass   # watermark update is best-effort; don't fail the delete

                # ── Delete matching (Attachments) folder if present ──────
                att_dir           = target.parent / (target.stem + " (Attachments)")
                attachments_count = 0
                bytes_freed       = 0
                if att_dir.is_dir():
                    for f in att_dir.rglob("*"):
                        if f.is_file():
                            try:
                                bytes_freed       += f.stat().st_size
                                attachments_count += 1
                            except Exception:
                                pass
                    shutil.rmtree(att_dir, ignore_errors=True)

                # ── Remove from in-memory index ───────────────────────────
                with _lock:
                    _state["notes"] = [n for n in _state["notes"]
                                       if n.get("file") != rel]

                self._json({
                    "ok":                 True,
                    "attachments_count":  attachments_count,
                    "bytes_freed":        bytes_freed,
                })
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

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

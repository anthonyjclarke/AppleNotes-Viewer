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
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

BASE_DIR = Path(__file__).parent
APP_HTML = BASE_DIR / "app.html"
PORT     = 8765

_CONFIG_FILE  = BASE_DIR / "config.json"
_SKIP_FOLDERS = {"Recently Deleted"}   # Apple Notes folders excluded from index

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


_DATE_PREFIX_STRIP = re.compile(r'^\d{4}-\d{2}-\d{2} ')
_HREF_SRC_RE       = re.compile(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', re.IGNORECASE)


def _referenced_attachments(html_path: Path, att_dir: Path) -> "set[str] | None":
    """Return the set of filenames inside att_dir that the note HTML references.

    Parses href/src attributes in the exported HTML and resolves them relative
    to the HTML file's directory. Only names whose resolved parent equals att_dir
    are included. Returns None when the file is too large to read safely (caller
    should leave the folder untouched). Never raises.
    """
    try:
        if html_path.stat().st_size > 10 * 1024 * 1024:
            return None   # base64-image-heavy notes; skip rather than read 10 MB
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
        for candidate in (raw, unquote(raw)):
            try:
                p = (html_dir / candidate).resolve()
                if p.parent == att_abs:
                    referenced.add(p.name)
                    break
            except Exception:
                pass
    return referenced


def _prune_orphan_attachments(notes_root: Path) -> dict:
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
      {files_removed, bytes_freed, items: [{note, file, size}], skipped, skip_reason}
    Never raises.
    """
    result: dict = {
        "files_removed": 0,
        "bytes_freed":   0,
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

    # Consistency gate: if the export folder is grossly out of sync with its own
    # manifest (interrupted export, external deletion, a cloud-sync tool like
    # Syncthing/Dropbox/iCloud propagating deletes into the folder), do NOT run
    # any cleanup. Require that most watermarked notes still exist on disk.
    present = 0
    for entry in entries.values():
        ep = entry.get("exportedPath", "") or ""
        if ep.endswith(".html") and (notes_root / ep).is_file():
            present += 1
    if entries and present < 0.75 * len(entries):
        reason = (
            f"Attachment cleanup skipped — export folder inconsistent "
            f"({present} of {len(entries)} notes on disk). "
            f"Folder may be in a cloud-sync share; see README.")
        result["skipped"]     = True
        result["skip_reason"] = reason
        with _lock:
            _state["sync_progress"]["current"] = reason
        return result

    # Scan every "(Attachments)" directory on disk. For each one, parse the
    # corresponding note HTML to find which files it actually references.
    # Anything not referenced in the HTML is an orphan and can be safely removed.
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

            note_title = _DATE_PREFIX_STRIP.sub("", stem)
            for child in att_dir.iterdir():
                if not child.is_file() or child.name in referenced:
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
                except Exception:
                    pass
        except Exception:
            continue
    return result


_DATE_PREFIX_RE = re.compile(r"(?:^|/)\d{4}-\d{2}-\d{2} ")


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
        if prefixed >= 0.80 * len(paths) else []


def _run_export_async(notes_root: Path, bin_path: str) -> None:
    """Run notes-export in a background thread, streaming progress into _state.

    Builds a structured sync_log dict throughout — covering export timing,
    all exporter stderr output, orphan cleanup detail, and re-index results —
    and stores it in _state["sync_log"] once the full sync + re-index completes.
    The log is available via GET /api/sync-log and powers the Sync Report modal.
    """
    def run():
        t0 = time.monotonic()
        log: dict = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type":    None,   # "full" | "incremental"
            "scheme":  None,   # "date_prefix" | "no_prefix"
            "export": {
                "duration_s":   0,
                "stderr_lines": [],   # last ≤500 lines for the UI
                "stderr_total": 0,    # all lines (may exceed capped list)
                "exit_code":    None,
                "error":        None,
            },
            "cleanup": {
                "files_removed": 0, "bytes_freed": 0,
                "items": [], "skipped": False, "skip_reason": None,
            },
            "reindex": {"notes_indexed": 0, "duration_s": 0},
            "total_duration_s": 0,
        }

        # ── Phase 1: full-export total (for % bar) ────────────────────
        watermark = notes_root / "AppleNotesExportSyncWatermark.json"
        is_full   = not watermark.exists()
        log["type"] = "full" if is_full else "incremental"
        if is_full:
            total = _count_notes_for_progress(bin_path)
            if total > 0:
                with _lock:
                    _state["sync_progress"]["total"] = total

        # ── Phase 2: detect filename scheme ───────────────────────────
        prefix_args = _detect_export_prefix_args(notes_root)
        log["scheme"] = "date_prefix" if prefix_args else "no_prefix"
        if prefix_args:
            with _lock:
                _state["sync_progress"]["current"] = (
                    "Existing notes use a date prefix — matching scheme…")

        # ── Phase 3: run the exporter ─────────────────────────────────
        t_export = time.monotonic()
        try:
            proc = subprocess.Popen(
                [bin_path, "export",
                 "--format", "html",
                 "--incremental",
                 "--verbose",
                 *prefix_args,
                 "--output", str(notes_root)],
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
                with _lock:
                    _state["sync_progress"]["done"]    = done
                    _state["sync_progress"]["current"] = line[:120]
                    sp_lines = _state["sync_progress"].get("lines")
                    if sp_lines is not None:
                        sp_lines.append(line)
                        # Keep most recent 1000 lines; trim if needed
                        if len(sp_lines) > 1000:
                            del sp_lines[:-800]
            proc.wait(timeout=300)
            log["export"]["duration_s"]   = round(time.monotonic() - t_export)
            log["export"]["stderr_total"] = done
            log["export"]["stderr_lines"] = stderr_lines[-500:]  # cap for UI
            log["export"]["exit_code"]    = proc.returncode
            if proc.returncode != 0:
                err = f"Export failed (exit {proc.returncode})"
                log["export"]["error"]  = err
                log["total_duration_s"] = round(time.monotonic() - t0)
                with _lock:
                    _state["sync_progress"].update({"active": False, "error": err})
                    _state["sync_log"] = log
                return
        except subprocess.TimeoutExpired:
            try: proc.kill()
            except Exception: pass
            err = "Export timed out after 5 minutes"
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

        # ── Phase 4: orphan attachment cleanup ────────────────────────
        try:
            with _lock:
                _state["sync_progress"]["current"] = "Cleaning up replaced attachments…"
            cleanup = _prune_orphan_attachments(notes_root)
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
        def _wait_for_reindex():
            while True:
                time.sleep(0.2)
                with _lock:
                    ip = dict(_state["index_progress"])
                if not ip.get("active", False):
                    with _lock:
                        note_count = len(_state["notes"])
                    log["reindex"]["notes_indexed"] = note_count
                    log["reindex"]["duration_s"]    = round(time.monotonic() - t_reindex)
                    log["total_duration_s"]         = round(time.monotonic() - t0)
                    log["log_complete"]             = True
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
             placeholder="PLACEHOLDER_PATH"
             value="CURRENT_PATH">
      <button class="browse-open-btn" id="browseOpenBtn" type="button">Browse…</button>
    </div>
    <p class="hint">PATH_TIP_TEXT</p>

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
            html = (_SETTINGS_HTML
                    .replace("CURRENT_PATH", current)
                    .replace("PLACEHOLDER_PATH", placeholder)
                    .replace("PATH_TIP_TEXT", tip))
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
                live_lines = list(_state["sync_progress"].get("lines", [])[-50:])
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

            with _lock:
                already = _state["sync_progress"].get("active", False)
            if already:
                self._json({"status": "syncing"})
                return

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

            with _lock:
                _state["sync_progress"] = {
                    "active": True, "done": 0, "total": 0,
                    "current": "Starting…", "error": None,
                    "lines": [],   # accumulated stderr lines for the live modal view
                }
            _run_export_async(notes_root, bin_path)
            self._json({"status": "syncing"})

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

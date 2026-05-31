# Archived Plan: Integrate apple-notes-exporter CLI

> **ARCHIVED — historical v2.0 planning document.** This file records the
> original Falcon Notes Exporter → `apple-notes-exporter` migration plan and is
> not a current operational guide. Several details below are intentionally
> superseded by the shipped app, including Recently Deleted handling, filename
> scheme detection, sync-report behavior, and capped indexing reads. Use
> [README.md](../README.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
> [API.md](API.md) for current v3.0 behavior.

## Context

The current app uses Falcon Notes Exporter (a manual browser-based tool). This plan replaces
it entirely with **apple-notes-exporter** (https://github.com/kzaremski/apple-notes-exporter),
a Swift CLI that reads Apple Notes' local SQLite database directly — both iCloud and On My Mac
accounts in a single command. v2.0 released April 28 2026; actively maintained.

**Goal:** Drive sync from a `sync.sh` script (and a "Sync Now" button in the UI). No
backward-compatibility with old Falcon exports is required — this is a clean cutover.

The implementation is split into two phases:

- **Phase 1** — Python app: config-driven Notes folder, browser settings page, sync UI
- **Phase 2** — Native .app: Swift wrapper with WKWebView, replacing the browser launch

---

## What the Real Export Looks Like

Export was validated against `Notes-New/` using default apple-notes-exporter settings
(HTML format, date prefix `yyyy-MM-dd`).

### Folder structure (Apple Notes folders ARE preserved)

```
{Notes Root}/
├── iCloud/
│   ├── Notes/                             ← 1,602 notes
│   │   ├── 2026-04-15 My Note.html
│   │   ├── 2026-04-15 My Note (Attachments)/
│   │   │   └── Document.pdf
│   │   └── …
│   └── Recently Deleted/                  ← 91 notes (excluded by default)
│       └── …
└── On My Mac/
    └── Archived/                          ← 980 notes
        └── …
```

Each Apple Notes folder becomes a subdirectory under its account name. The depth is always
`{Account}/{Folder}/{Note}.html` — confirmed depth 3 from the Notes root. Attachment
subdirectories (`{yyyy-MM-dd} {Title} (Attachments)/`) are at depth 4 and are correctly
excluded by the depth filter.

### Format details confirmed

| Item                  | Format                                                                 |
|:----------------------|:-----------------------------------------------------------------------|
| Filename              | `{yyyy-MM-dd} {Title}.html`                                            |
| Attachment folder     | `{yyyy-MM-dd} {Title} (Attachments)/`                                  |
| Attachment types      | PDF, PNG, JPEG, TIFF, HEIC (all relative `href`/`src` paths)           |
| Images in note body   | `data:image/...;base64,...` inline — no path rewriting needed          |
| Date meta tags        | `<meta name="modified" content="D Mon YYYY at H:MM am/pm">`            |
| mtime                 | Set to note's last-edit date — confirmed accurate (50-note spot-check) |

### "Recently Deleted" folder

The export includes a "Recently Deleted" Apple Notes folder. Default behaviour: exclude it
from the index (add a `_SKIP_FOLDERS` set in `server.py`). This can be made configurable
via the settings page later.

---

## Known Limitations

### 01-01-2001 epoch dates (≈23% of notes)

414 of 1,758 iCloud notes had `<meta name="modified" content="1 Jan 2001…">` and mtime of
1 January 2001. This is genuine data from Apple Notes' SQLite database — these notes have no
valid date recorded (common for very old, imported, or migrated notes). They sort to the
bottom of the list. This is not a bug — it reflects what Apple Notes itself stores. A future
enhancement could group them in an "Undated" section.

---

## Known Unknowns

| Unknown                     | Status                                                                 |
|:----------------------------|:-----------------------------------------------------------------------|
| mtime preservation          | ✅ RESOLVED — matches note's last-edit date                            |
| Attachment path format      | ✅ RESOLVED — `{Title} (Attachments)/{filename}` (opt. `YYYY-MM-DD ` prefix) |
| Account directory names     | ✅ RESOLVED — `iCloud`, `On My Mac`                                    |
| Apple Notes folder hierarchy | ✅ RESOLVED — preserved; each folder is a subdirectory under account  |
| Incremental delete handling | ⚠️ UNKNOWN — does `--incremental` remove HTML for deleted notes?      |
| Sync manifest               | ✅ RESOLVED — `AppleNotesExportSyncWatermark.json` at export root, keyed by `exportedPath` + `modificationDate` |

---

## Phase 1 — Python App

### Step 1 — `config.json` and NOTES_ROOT

**Problem:** The Notes folder will live in the user's Documents folder (for backup), not next
to the app. NOTES_ROOT must be configurable.

**Config file:** `config.json` alongside `server.py`:
```json
{
  "notes_root": "/Users/ant/Documents/AppleNotes"
}
```

`server.py` reads this on startup:
```python
import json
_CONFIG_FILE = BASE_DIR / "config.json"

def load_config() -> dict:
    if _CONFIG_FILE.exists():
        return json.loads(_CONFIG_FILE.read_text())
    return {}

config = load_config()
NOTES_ROOT = Path(config["notes_root"]) if config.get("notes_root") else None
```

If `NOTES_ROOT` is `None` (no config), the server starts but serves only the `/settings`
page — all other routes redirect to `/settings`.

### Step 2 — `/settings` page in `server.py`

Add a `/settings` route that serves an HTML page (styled to match the app) with:
- A text field pre-populated with the current `notes_root` value
- A **Save** button that POSTs to `/settings` and writes `config.json`
- After save: redirect to `/` and trigger a re-index

Also add a settings link/icon in the `app.html` sidebar so the user can return to it.

The `/settings` page is also the landing page shown on first run when no config exists.

**`GET /settings`** — serve settings HTML  
**`POST /settings`** — body: `{"notes_root": "/path/to/folder"}` — validates path exists,
writes `config.json`, calls `_rebuild()`, returns `{"status": "ok"}` or `{"status": "error"}`

### Step 3 — `server.py`: depth filter + exclusions + threading + meta date

1. **Import** `threading`, `subprocess`. Switch `HTTPServer` → `ThreadingHTTPServer`.

2. **Skip folders:**
   ```python
   _SKIP_FOLDERS = {"Recently Deleted"}   # configurable via settings later
   ```
   In `build_index()`, after computing `parts`:
   ```python
   if len(parts) != 3:
       continue
   if parts[1] in _SKIP_FOLDERS:
       continue
   ```
   This replaces the old `_ASSET_DIRS` name check — no longer needed.

3. **File identity:** store `file` as NOTES_ROOT-relative path:
   ```python
   "file": "/".join(parts),   # e.g. "iCloud/Notes/2026-04-15 My Note.html"
   ```

4. **Date source — `<meta name="modified">` with mtime fallback:**
   ```python
   # In NoteParser.__init__:
   self.modified = ""

   # In NoteParser.handle_starttag:
   if tag == "meta":
       attr_d = dict(attrs)
       if attr_d.get("name") == "modified":
           self.modified = attr_d.get("content", "")

   # In build_index():
   date = None
   if p.modified:
       try:
           date = datetime.strptime(p.modified, "%d %b %Y at %I:%M %p")
       except ValueError:
           pass
   if date is None:
       date = datetime.fromtimestamp(html_file.stat().st_mtime)
   ```
   The meta tag survives file copies and rsync; mtime is the fallback for notes without it.

5. **NoteParser filename fallback** — the date-prefix regex should match `yyyy-MM-dd` format:
   ```python
   # Strip leading "YYYY-MM-DD " from filename when <title> tag is absent
   import re
   stem = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", html_file.stem)
   ```

6. **Threaded state:**
   ```python
   _lock = threading.Lock()
   _state: dict = {}
   ```
   Move `ALL_NOTES`, `CLIENT_INDEX`, `FOLDERS`, `TAGS` into `_state`. Swap atomically under
   the lock inside a `_rebuild()` helper. All route handlers read from `_state` under the lock.

7. **`/api/sync` endpoint:**
   - `GET` → `{"last_synced": isostr_or_null, "count": int}`
   - `POST` → runs `bash sync.sh` (timeout 300 s), calls `_rebuild()`, returns
     `{"status": "ok", "count": int}` or `{"status": "error", "message": str}`

### Step 4 — `sync.sh` (new file)

```sh
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${NOTES_EXPORT_BIN:-notes-export}"
CONFIG="$SCRIPT_DIR/config.json"

if ! command -v "$BINARY" &>/dev/null; then
  echo "ERROR: 'notes-export' not found in PATH." >&2
  echo "  Set NOTES_EXPORT_BIN=/path/to/notes-export or add to /usr/local/bin/" >&2
  exit 1
fi

NOTES_ROOT=$(python3 -c "import json,sys; print(json.load(open('$CONFIG'))['notes_root'])")

"$BINARY" export \
  --format html \
  --incremental \
  --output "$NOTES_ROOT"
```

> **Note on `--incremental`:** This flag is added explicitly for performance — it is not a
> default apple-notes-exporter option. On the first run (no manifest present) it performs a
> full export *and* writes the manifest. On subsequent runs it only processes changed notes.
> **Confirmed:** the manifest is `AppleNotesExportSyncWatermark.json`, written to the export
> root, keyed by each note's `exportedPath` and `modificationDate`. Use it from the first
> run so the manifest exists for later fast syncs. `--reset-sync` force-deletes the manifest
> and is only effective together with `--incremental`.

> **Filename-scheme consistency (critical).** The exporter's default names files
> `{Title}.html` — **no date prefix**. `--add-date-prefix` (+ `--date-format iso|us|eu`)
> prefixes the note's *creation* date, giving `YYYY-MM-DD {Title}.html`. Because the
> incremental manifest keys on `exportedPath`, running the export under a *different*
> scheme than the existing files makes every note look new: the exporter writes a parallel
> set under the new names, leaves the old files untouched, and the note count silently
> ~doubles. The Sync command (`_run_export_async`, `sync.sh`) uses the no-prefix default,
> so any initial/manual export must also be no-prefix. Recovery from a mixed folder:
> delete the export root contents *including the manifest*, then re-run the no-prefix
> export. The viewer strips a leading `YYYY-MM-DD ` prefix anyway (it is cosmetic and
> never a date source), so no-prefix loses nothing.

### Step 5 — `app.html`: attachment rewriter + sync UI + settings link

**Attachment rewriter** — broaden from `attachments/` prefix to any relative path, covering
all attachment types (PDF, PNG, JPEG, TIFF, HEIC):

```javascript
// Rewrite relative attachment hrefs — apple-notes-exporter format:
// "2026-04-15 My Note (Attachments)/Document.pdf"
// "2026-04-15 My Note (Attachments)/Pasted Graphic.png"
body.querySelectorAll("a[href]").forEach(a => {
  const href = a.getAttribute("href") || "";
  if (href && !href.match(/^(https?:|data:|#|\/)/)) {
    a.setAttribute("href", `/static/${folderPath}/${href}`);
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener");
  }
});
body.querySelectorAll("embed[src], object[data]").forEach(el => {
  const attr = el.tagName === "OBJECT" ? "data" : "src";
  const val  = el.getAttribute(attr) || "";
  if (val && !val.match(/^(https?:|data:|#|\/)/)) {
    el.setAttribute(attr, `/static/${folderPath}/${val}`);
  }
});
```

**Sync UI** — add to sidebar (below folder list, before `</aside>`):
```html
<div class="sync-footer" id="syncFooter">
  <span class="sync-status" id="syncStatus">—</span>
  <button class="sync-btn" id="syncBtn" title="Sync notes now">↻ Sync</button>
</div>
```

**Settings link** — add a gear icon/link in the sidebar header that navigates to `/settings`.

**Sync JS** (add before `init()`):
```javascript
async function loadSyncStatus() {
  try {
    const r = await fetch("/api/sync");
    const d = await r.json();
    const el = document.getElementById("syncStatus");
    if (!d.last_synced) { el.textContent = "Not yet synced"; return; }
    const diff = Math.round((Date.now() - new Date(d.last_synced)) / 60000);
    el.textContent = diff < 1 ? "Synced just now"
      : diff < 60 ? `Synced ${diff}m ago`
      : `Synced ${Math.round(diff/60)}h ago`;
  } catch { /* sync not yet configured */ }
}

document.getElementById("syncBtn").addEventListener("click", async () => {
  const btn = document.getElementById("syncBtn");
  btn.disabled = true; btn.textContent = "↻ Syncing…";
  try {
    const r = await fetch("/api/sync", { method: "POST" });
    const d = await r.json();
    if (d.status === "ok") {
      document.getElementById("syncStatus").textContent = "Synced just now";
      await loadFolders(); await loadTags();
      updateSearchAllPill(); await loadNoteList();
    } else {
      alert("Sync failed: " + (d.message || "unknown error"));
    }
  } catch (e) { alert("Sync error: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "↻ Sync"; }
});
```

Add `loadSyncStatus()` (fire-and-forget) at the end of `init()`.

### Step 6 — `Launch Notes.command`: optional auto-sync

```bash
if [[ "${1:-}" == "--sync" ]] || [[ "${AUTO_SYNC:-}" == "1" ]]; then
  echo "Syncing notes…"
  bash sync.sh || echo "⚠ Sync failed — launching with existing notes"
fi
```

### Step 7 — Documentation

**README.md:** Replace Falcon workflow. Requirements: download `notes-export` binary, place in
`/usr/local/bin/`, grant Full Disk Access in System Settings > Privacy & Security. Setup:
run app → browser opens `/settings` → enter Notes folder path → run `bash sync.sh`. Document
`AUTO_SYNC=1` env var and "Recently Deleted" exclusion behaviour.

**NOTES_VIEWER.md:** Update folder layout diagram to show `{Account}/{Folder}/{Note}.html`
structure with the confirmed account/folder names. Add `/api/sync` and `/settings` to the
technical reference. Add "Full Disk Access" troubleshooting entry.

---

## Phase 2 — Native .app Wrapper

A minimal Swift app that hosts the existing web UI in a `WKWebView` window. No browser
required. The Python server runs as a background subprocess.

### Architecture

```
AppleNotesViewer.app/
├── Contents/
│   ├── MacOS/
│   │   └── AppleNotesViewer        ← Swift binary
│   ├── Resources/
│   │   ├── server.py               ← bundled alongside
│   │   └── AppIcon.icns
│   └── Info.plist
```

The Swift app:
1. Locates `server.py` inside the bundle's `Resources/`
2. Launches `python3 server.py` as a `Process()` subprocess
3. Opens a `WKWebView` window loading `http://127.0.0.1:8765`
4. Terminates the subprocess on quit

### Configuration in Phase 2

Config moves from `config.json` (next to server.py) to:
```
~/Library/Application Support/AppleNotesViewer/config.json
```

`server.py` searches both locations (bundle Resources first, then `~/Library/...`), so the
same server.py works in Phase 1 (next to the file) and Phase 2 (in the bundle).

### Menu bar actions

| Menu item                  | Action                                                         |
|:---------------------------|:---------------------------------------------------------------|
| File > Sync Now            | POST to `/api/sync`, reload WKWebView on completion            |
| AppleNotesViewer > Preferences… | Load `/settings` in the WKWebView                        |
| AppleNotesViewer > Quit    | Terminate subprocess, exit app                                 |

### Native folder picker in Settings

The `/settings` page has a "Choose Folder…" button. In Phase 1 this is a plain text input.
In Phase 2, the button sends a JavaScript message to Swift via `WKScriptMessageHandler`:

```javascript
// In settings page JS:
window.webkit.messageHandlers.chooseFolderBtn.postMessage({});
```

Swift handler shows `NSOpenPanel` (canChooseDirectories: true), then injects the result back:

```swift
webView.evaluateJavaScript("document.getElementById('notesRootInput').value = '\(selectedPath)'")
```

The user then clicks Save as normal — the Python server writes config and re-indexes.

### Code signing

For local/personal use: ad-hoc signing (`codesign --sign -`). For sharing: sign with an
Apple Developer ID (free account sufficient for direct distribution, no App Store).

### Implementation steps for Phase 2

1. Create Xcode project (macOS App, Swift, AppKit, no SwiftUI)
2. `AppDelegate.swift` — start/stop subprocess, create `NSWindow` with `WKWebView`
3. Add menu items wired to `AppDelegate` actions
4. Copy `server.py` into bundle Resources via a Copy Files build phase
5. Implement `WKScriptMessageHandler` for folder picker
6. Add app icon (`AppIcon.icns`)
7. Update `config.json` path resolution in `server.py` to check both locations
8. Ad-hoc sign and test

---

## Performance Note

Notes with inline base64 images can be 1–6 MB each. `build_index()` currently loads each
file in full. For 2,600+ notes this is manageable at startup but wasteful for large files.

Future optimisation: read only the first 8 KB per file to extract `<title>` and `<meta>` tags
(both are in `<head>`, well within this range), then cap the body read for the search snippet.
Not a blocker for Phase 1.

---

## Phase 1 Verification

1. Run app with no `config.json` → browser opens `/settings` page
2. Enter Notes folder path → save → notes index builds → sidebar appears
3. Run `bash sync.sh` → `Notes-New/` fills with `{Account}/{Folder}/{yyyy-MM-dd} {Title}.html`
4. Open a note with an image → renders inline (base64, no rewriting)
5. Open a note with a PDF/image attachment → attachment renders (broadened rewriter)
6. Click "Sync Now" → spinner → POST `/api/sync` → note list refreshes
7. Confirm "Recently Deleted" notes do NOT appear in sidebar
8. Confirm notes sorted by last-edited date; 01-01-2001 notes at bottom

---

## Files to Change

**Phase 1**
- **Modified:** `server.py`, `app.html`, `Launch Notes.command`, `README.md`, `NOTES_VIEWER.md`
- **New:** `sync.sh`, `config.json` (user-created via settings page, gitignored)
- **Untouched:** `make_demo.py`, demo Notes/ data

**Phase 2**
- **New:** Xcode project (`AppleNotesViewer/`), `AppDelegate.swift`, `Info.plist`, `AppIcon.icns`
- **Modified:** `server.py` (config path resolution), `README.md` (app installation instructions)

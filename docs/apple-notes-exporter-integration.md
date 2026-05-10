# Plan: Integrate apple-notes-exporter CLI

## Context

The current app relies on the Falcon web exporter (https://falcon.star-lord.me/exporter), a manual browser-based tool. The user must visit the site, export, and copy files — a multi-step process that doesn't easily unify iCloud and On My Mac notes together.

**apple-notes-exporter** (https://github.com/kzaremski/apple-notes-exporter) is a Swift CLI that reads the Apple Notes local SQLite database directly — both iCloud and On My Mac accounts in a single command. Its `--incremental` flag tracks changes via a manifest, making re-syncs fast. v2.0 was released April 28 2026; 484 stars, actively maintained.

**Goal:** Replace the manual Falcon workflow with a CLI-driven `sync.sh` that keeps Notes/ current automatically, and add a "Sync Now" button to the UI. Maintain backward compatibility with existing Falcon-exported notes.

---

## What Changes and Why

### Format differences to handle

| Concern | Falcon | apple-notes-exporter | Action required |
|:---|:---|:---|:---|
| Images | `images/UUID.jpg` (relative file) | `data:image/...;base64,...` (inline) | No action — base64 URIs don't match `startsWith("images/")` rewriter; safely ignored |
| Attachments | `attachments/UUID.pdf` | `{NoteTitle}/attachment.pdf` | Broaden rewriter from `attachments/` prefix to any relative path |
| Filenames | `{Title}-DD-MM-YYYY.html` | `{Title}.html` | No action — title already extracted from `<title>` tag |
| Folder depth | `{Account}/{Folder}/{Note}.html` (depth 3) | `{Account}/{Folder}/{Note}.html` (depth 3) | Compatible — same structure |
| Asset subdirs | `images/`, `attachments/` | No `images/`; `{NoteTitle}/` for attachments | Depth filter replaces dir-name exclusion |

### File identity issue (existing bug, fix here)

`server.py:198` looks up notes by bare filename: `n["file"] == fname`. Two notes named `Shopping List.html` in different folders would collide. Fix: store `file` as a NOTES_ROOT-relative path (e.g., `iCloud/Personal/Shopping List.html`). This is also used in `app.html` as `data-file` on list items and in `openNote(file)` — updating the stored value propagates correctly with no other logic changes needed.

---

## Known Unknowns (validate before full implementation)

These must be verified against a real apple-notes-exporter export:

1. **mtime preservation** — does the CLI set each file's mtime to the note's last-edit date (like Falcon), or to export time? If export time, date sorting will be wrong and an alternative date source is needed (manifest.json, or a `<meta>` tag in the HTML).
2. **Attachment path format** — inspect the actual `<a href>` and `<embed src>` values inside an exported HTML file for a note with a PDF attachment. The broadened rewriter must match exactly.
3. **Account directory names** — what does apple-notes-exporter call the account dirs? ("iCloud", "On My Mac", or email address?) Affects README examples.
4. **Incremental delete handling** — does `--incremental` remove HTML files for notes deleted from Apple Notes, or only add/update? If not, stale notes accumulate until a full re-export.

**Validation step:** Before writing any sync UI, run `notes-export export --format html --output /tmp/test-export` on a real Notes database and inspect the output structure.

---

## Implementation

### Step 1 — `server.py`: file identity fix + depth filter + threading

**Files:** `server.py`

**Changes:**

1. Import `threading` and `subprocess`. Change `HTTPServer` → `ThreadingHTTPServer` (prevents the /api/sync endpoint from blocking the UI during a long sync).

2. In `build_index()` at line 125, change `"file"` to store relative path:
   ```python
   # Before:
   "file": html_file.name,
   # After:
   "file": "/".join(parts),   # e.g. "iCloud/Personal/Shopping List.html"
   ```

3. In `build_index()` at line 96, replace the `_ASSET_DIRS` check with a depth filter:
   ```python
   # Before:
   if any(p in _ASSET_DIRS for p in parts[:-1]):
       continue
   # After:
   if len(parts) != 3:   # only index {Account}/{Folder}/{Note}.html
       continue
   ```
   Remove `_ASSET_DIRS` constant (line 23) — no longer needed.

4. Add global state dict protected by a lock, replacing the module-level globals:
   ```python
   _lock = threading.Lock()
   _state: dict = {}
   ```
   Move `ALL_NOTES`, `CLIENT_INDEX`, `FOLDERS`, `TAGS` into `_state` via a `_rebuild()` helper. Swap atomically under the lock on each rebuild. All route handlers read from `_state` under the lock.

5. Add `/api/sync` endpoint:
   - `GET /api/sync` → returns `{"last_synced": isostr_or_null, "count": int}`
   - `POST /api/sync` → runs `bash sync.sh` (timeout 300s), calls `_rebuild()`, returns `{"status": "ok", "count": int}` or `{"status": "error", "message": str}`

6. Update `do_GET` at line 198 — the `n["file"] == fname` lookup now works correctly since both sides use the relative path.

### Step 2 — `sync.sh` (new file)

```sh
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${NOTES_EXPORT_BIN:-notes-export}"

if ! command -v "$BINARY" &>/dev/null; then
  echo "ERROR: 'notes-export' not found in PATH." >&2
  echo "  Set NOTES_EXPORT_BIN=/path/to/notes-export or add it to /usr/local/bin/" >&2
  exit 1
fi

"$BINARY" export \
  --format html \
  --incremental \
  --output "$SCRIPT_DIR/Notes"
```

Incremental flag uses apple-notes-exporter's `manifest.json` (written inside Notes/). First run is a full export; subsequent runs only process changed notes — typically seconds.

`Notes/manifest.json` is already excluded by the existing `Notes/*` gitignore rule.

### Step 3 — `app.html`: attachment rewriter + sync UI

**Attachment rewriter** (around line 905–922):

The current rewriter only handles `attachments/` prefix. Broaden to any relative path (matches both Falcon and apple-notes-exporter):

```javascript
// Rewrite attachment hrefs — handles both:
//   Falcon:  attachments/UUID.pdf
//   apple-notes-exporter: {NoteTitle}/filename.pdf
body.querySelectorAll("a[href]").forEach(a => {
  const href = a.getAttribute("href") || "";
  if (href && !href.match(/^(https?:|data:|#|\/)/)) {
    a.setAttribute("href", `/static/${folderPath}/${href}`);
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener");
  }
});
// Same pattern for embed[src] and object[data]
body.querySelectorAll("embed[src], object[data]").forEach(el => {
  const attr = el.tagName === "OBJECT" ? "data" : "src";
  const val  = el.getAttribute(attr) || "";
  if (val && !val.match(/^(https?:|data:|#|\/)/)) {
    el.setAttribute(attr, `/static/${folderPath}/${val}`);
  }
});
```

**Sync UI** — add to sidebar HTML (below folder list, before `</aside>`):

```html
<div class="sync-footer" id="syncFooter">
  <span class="sync-status" id="syncStatus">—</span>
  <button class="sync-btn" id="syncBtn" title="Sync notes now">↻ Sync</button>
</div>
```

CSS additions (inside `<style>`):
```css
.sync-footer {
  flex-shrink: 0;
  padding: 8px 14px 12px;
  border-top: 1px solid var(--divider);
  display: flex; align-items: center; gap: 8px;
}
.sync-status {
  flex: 1; font-size: 11px; color: var(--tx-tertiary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sync-btn {
  flex-shrink: 0; padding: 4px 10px; border-radius: 7px;
  border: 1px solid var(--border); background: transparent;
  color: var(--tx-secondary); font-size: 12px; font-family: inherit;
  cursor: pointer; transition: all var(--trans);
}
.sync-btn:hover { border-color: var(--accent); color: var(--tx-primary); }
.sync-btn:disabled { opacity: 0.4; cursor: default; }
```

JS (add before `init()`):
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
  } catch { /* server may not support sync — silently hide status */ }
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

Add `loadSyncStatus()` call inside `init()` (non-blocking, fire-and-forget):
```javascript
async function init() {
  await loadFolders();
  await loadTags();
  updateSearchAllPill();
  await loadNoteList();
  loadSyncStatus();   // ← add
}
```

### Step 4 — `Launch Notes.command`: optional auto-sync

Existing launcher kills port 8765, starts server, opens browser. Add optional pre-launch sync:

```bash
# Before starting server, optionally run sync (set AUTO_SYNC=1 or pass --sync arg)
if [[ "${1:-}" == "--sync" ]] || [[ "${AUTO_SYNC:-}" == "1" ]]; then
  echo "Syncing notes…"
  bash sync.sh || echo "⚠ Sync failed — launching with existing notes"
fi
```

### Step 5 — Documentation

**README.md:**
- Replace Falcon as primary workflow with apple-notes-exporter
- New "Requirements" section: download `notes-export` binary from GitHub Releases, place in `/usr/local/bin/`, grant Full Disk Access in System Settings > Privacy & Security
- Replace "Export from Falcon" steps with `bash sync.sh` (or UI Sync button)
- Add "Backward compatibility" note: existing Falcon exports in Notes/ continue to work
- Document `AUTO_SYNC=1` env var for the launcher

**NOTES_VIEWER.md:**
- Update folder layout diagram to show apple-notes-exporter output structure
- Add `/api/sync` to the technical reference table
- Add "Full Disk Access" troubleshooting entry

---

## Verification

1. Install `notes-export` binary and grant Full Disk Access
2. Run `bash sync.sh` — confirm Notes/ fills with `{Account}/{Folder}/{Note}.html` files
3. Start server and open http://127.0.0.1:8765 — confirm notes appear in sidebar
4. Open a note with an image — confirm image renders (base64 inline, no path rewriting)
5. Open a note with a PDF attachment — confirm PDF link opens (broadened rewriter)
6. Click "Sync Now" in UI — confirm spinner, POST to `/api/sync`, note list refreshes
7. Test with existing Falcon-exported Notes/ — confirm depth-3 notes still indexed

---

## Files to Change

- **Modified:** `server.py`, `app.html`, `Launch Notes.command`, `README.md`, `NOTES_VIEWER.md`, `.gitignore`
- **New:** `sync.sh`
- **Untouched:** `make_demo.py`, `NOTES_VIEWER.md` (except sync section), demo Notes/ data

# Apple Notes Viewer — CLAUDE.md

## What this project is

Local single-page web app for browsing and searching Apple Notes exports produced by
[`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter) CLI.
v2.6.0 — Python 3 stdlib only, no framework, no build step.

---

## Architecture

| File | Role |
|:-----|:-----|
| `server.py` | Python 3 `ThreadingHTTPServer` — indexes notes, serves API + static files |
| `app.html` | Single-file SPA — all CSS and JS inline |
| `sync.sh` | Shell wrapper: calls `notes-export export --incremental`, reads path from `config.json` |
| `Launch Notes.command` | Double-click Finder launcher — kills old instance, opens browser |
| `config.json` | Gitignored — `{"notes_root": "/abs/path/to/export"}` |

---

## Key architectural decisions and WHY

**Async startup** — server binds immediately; indexing runs in a daemon thread.
`_state["notes_root"]` and `_state["index_progress"]["active"] = True` are set from
config *before* the HTTP server starts, so the first-run redirect guard works instantly.

**Race condition guard** — POST `/settings` and POST `/api/sync` set
`_state["index_progress"]["active"] = True` *before* calling `_start_rebuild_async()`.
Without this, the client's first poll sees stale `active: False` and redirects with old data.

**Thread-safe state** — single `_state` dict + `_lock`. `_rebuild()` swaps state
atomically. Each request calls `_snap()` → shallow copy only.

**`notes_root` vs `configured_root`** — `_state["notes_root"]` is only set when the
folder exists; `_state["configured_root"]` always holds the raw config string. Settings
falls back to `configured_root` so a stale path from another Mac shows in the field.

**First-run guard exceptions** — `_SETTINGS_PATHS = {"/settings", "/favicon.ico",
"/api/browse"}`. The browse API must be in this set; if excluded, the Settings page
folder picker silently fails whenever `notes_root` is `None`.

**Export depth filter** — exporter produces `{Account}/{Folder}/{Title}.html` (depth 3;
optional `YYYY-MM-DD ` prefix). `len(f.relative_to(notes_root).parts) == 3` is the only
filter; attachment subdirs (depth 4) skipped. `_SKIP_FOLDERS = set()` (empty — nothing
is hard-excluded). `_RECENTLY_DELETED_FOLDERS` (lowercase) = `{"recently deleted",
"trash", "deleted items"}` — notes in these folders are indexed and shown everywhere but
flagged `recently_deleted: True` in the note dict and client index. See below.

**Per-segment URL encoding** — folder names can contain `#` (Apple Notes hashtag
folders). Path segments are encoded individually with `encodeURIComponent` so `#`
becomes `%23`, not a URL fragment. The static handler uses `unquote()` to decode.

**Date source** — `<meta name="modified" content="D Mon YYYY at H:MM am/pm">` parsed
first; mtime is the fallback (survives rsync/OS migration that corrupts mtime). The
`YYYY-MM-DD ` filename prefix is stripped (lines 174, 193) and is **never** a date
source — purely cosmetic. The exporter's default is *no* prefix; `--add-date-prefix`
adds the creation date. A scheme mismatch vs. existing files makes the incremental
manifest treat every note as new → silent whole-library duplication. `_run_export_async`
calls `_detect_export_prefix_args()` to auto-match the existing scheme (watermark
`exportedPath`s, else on-disk scan; ≥80% date-prefixed → `--add-date-prefix
--date-format iso`). `sync.sh` does NOT auto-detect — only the in-app Sync does.

**Tag extraction — dual source, two thresholds** — apple-notes-exporter embeds Apple
Notes' native tags in the filename stem (e.g. `2026-04-12 Meeting #work.html`). These
are `_stem_tags` (authoritative, shown if count ≥ 1). Body text also scanned for
`body_tags` (shown only if ≥ 2, noise filter). `_TAG_RE` matches letter-start tags ≥ 2
chars (`#AI`) and digit-start tags with ≥ 1 letter (`#10SmallSt`, `#60thBigBash`).

**PDF rendering — `<iframe>` replacement, live DOM only** — `<embed>`/`<object>` and
`data-pdf-href` attachment cards are replaced with `<iframe>` in the live DOM. URL
rewriting must not happen in the detached DOMParser doc — Chrome's `innerHTML` serialiser
decodes `%23` back to `#`. Only the outermost `[data-pdf-href]` element is replaced;
inner ones are skipped via `closest()`. Delegated click listener on `#contentPanel`
with a `.pdf` href fallback catches any card the marking pass missed.

**Hashtag `<h1>` suppression** — the exporter splits "Title #tag" into multiple `<h1>`
elements per token. `renderNote()` Step 4 hides subsequent `<h1>`s whose text is solely
`#hashtag` tokens, preventing duplicate heading clutter in the rendered note.

**Indeterminate scan phase** — `build_index()` calls `rglob("*.html")` before the total
count is known. When `index_progress.total == 0`, the startup overlay and Settings
progress bar show an animated sweep + "Scanning notes folder…" instead of "0 / 0".

**`notes-export` binary probe** — Finder/launchd strip PATH to a minimal set, so
`shutil.which("notes-export")` fails when launched via `Launch Notes.command`.
`_find_notes_export_bin()` probes five hardcoded paths, including the app bundle at
`/Applications/Apple Notes Exporter.app/Contents/SharedSupport/notes-export`. `sync.sh`
applies the same probe. Never rely on PATH alone for this binary.

**Exporter `<pre>` fragmentation** — `apple-notes-exporter` wraps every text run between
bold markers in its own `<pre style='background:#f5f5f5'>` element. `renderNote()` Step 5
collapses consecutive runs (fingerprint: `background:\s*#f5f5f5` on the style attribute),
merges their `innerHTML`, strips `**` bold delimiters, converts markdown headings/bullets/
pipe-tables, and outputs a single `.exporter-prose` div. All processing is on live DOM
nodes — never on a detached/serialised document (see PDF `%23` gotcha above).

**Sync progress state** — `_state["sync_progress"]` holds `{active, done, total, current,
error}`. POST `/api/sync` sets `active: True` before spawning `_run_export_async()`;
GET `/api/sync` includes the full `sync_progress` snapshot. The client polls GET during
export (via `pollSyncProgress`), then hands off to `pollIndexProgress` for re-indexing.
`done` is the **stderr-line count** from `--verbose`, NOT a note count (freeform
stream, >1 line/note — it overshoots the real total). `total` is only set for a
*full* export (no watermark) via `list-notes`; the client clamps `done` to it for a
% bar. Incremental leaves `total` 0 → honest indeterminate sweep, no number. Never
parse `current`/stderr into a note name (that produced garbage like `1683]`).

**Benign no-op is success** — `notes-export` exits non-zero when there's nothing to
export ("All notes are up to date, nothing to export."). The export phase scans
stderr for benign-no-op phrases ("nothing to export", "all notes are up to date",
"no notes to export", "no changes"); if matched, a non-zero exit is NOT treated as
failure and `exit_code` is normalised to 0. Never revert to a bare
`if proc.returncode != 0` failure check — an unchanged library exits non-zero.

**Sync log** — `_state["sync_log"]` is a structured dict built by `_run_export_async`
across all phases: `{timestamp, type, scheme, export:{duration_s, stderr_lines[-500:],
stderr_total, exit_code, error, exporter_total, deleted_notes:[path,…]},
cleanup:{files_removed, bytes_freed, dirs_removed, items:[{note,file,size}], skipped,
skip_reason}, reindex:{notes_indexed, duration_s}, drift:{detected, stale_count, indexed,
exporter_total}, full_log:[…], total_duration_s}`. `full_log` is the entire run —
exporter stderr + cleanup action lines — captured from `sync_progress["lines"]` after
cleanup; the report's top pane renders it as a tall scrollable terminal
(`.synclog-live-pre.review`). `_wait_for_reindex` thread writes the final log once
`index_progress.active` goes False. Served by `GET /api/sync-log`; powers the Sync
Report modal. `GET /api/sync` also returns `live_lines` — last 50 of
`sync_progress["lines"]` — for the live output pane. `sync_progress["lines"]`
accumulates stderr lines in-memory (capped at 1000; last 800 kept when trimmed).
`_emit_sync_line()` is the thread-safe appender used by the cleanup phase to stream
`✗ orphan removed` / `✗ empty folder removed` lines into that buffer so they appear
in both the live pane and `full_log`. `_prune_orphan_attachments` returns a dict (not
tuple) with `items` per deleted file so the modal can show a per-note × per-file
cleanup table.

**Deleted-notes detection** — `apple-notes-exporter --verbose` emits
`Deleted (no longer in Notes): <path>` lines for notes it previously exported that
have since been removed from Apple Notes. The exporter updates its watermark for these
but does **not** delete the HTML from disk. `_DELETED_NOTE_RE` captures these lines
during the stderr loop; paths are deduplicated and stored in
`log["export"]["deleted_notes"]`. The Sync Report renders a "Deleted from Apple Notes"
phase card listing each file with individual **Remove** buttons and a bulk **Remove all**
button — both call `POST /api/note/delete`. A drift banner is also shown when the
count-based threshold fires (≥ 10 notes or 2% over the exporter total). The two signals
are complementary: `deleted_notes` gives exact paths from this sync's verbose output;
the drift banner catches accumulated old deletions not in that list.

**Force Full Re-export (`reset_sync`)** — `POST /api/sync` accepts
`{"reset_sync": true}`; the flag flows through to
`_run_export_async(notes_root, bin_path, reset_sync=True)`, which appends
`--reset-sync` to the exporter command (still combined with `--incremental` — the
exporter requires both). The watermark is wiped before the export runs, so every note
is treated as new and re-exported to its current Apple Notes location. **This is the
only signal the app has for Apple-Notes-internal folder moves** (most importantly,
notes moved into Recently Deleted) — the incremental exporter cannot detect them
because `modificationDate` does not change on a folder move. After a `reset_sync`
run, `_detect_stale_html_files()` scans the fresh watermark's `exportedPath` set
against on-disk HTML files at depth 3 and returns those not matched. Results land in
`log["stale_files"]` as `[{path, title, size}, …]`. The Sync Report renders a "Stale
HTML files on disk" card with the same per-row Remove + bulk Remove-all pattern as
"Deleted from Apple Notes". Never call `_detect_stale_html_files()` after a normal
(non-reset) sync — the cumulative watermark contains entries for notes deleted years
ago whose files do still exist, so on-disk files would be incorrectly flagged. The
client wires Force Full Re-export through `confirmForceFullReExport()` →
`runSync(true)`; both the sidebar `#syncForceLink` and the drift banner's
`.synclog-force-btn` call into it. The confirmation dialog is intentionally a plain
`window.confirm()` — modal overlays would conflict with the live sync report opening.

**Recently Deleted indexing** — `_SKIP_FOLDERS` is now empty. Notes in
`_RECENTLY_DELETED_FOLDERS` are indexed normally but carry `recently_deleted: True` in
the note dict (not `_`-prefixed, so it passes through to the client index). The client
uses this field in two places: (1) `renderList()` adds a `.is-deleted-note` CSS class
and a `.note-deleted-pill` badge (`🗑 Recently Deleted`) between the title row and the
snippet; (2) `renderNote()` inserts a `.recently-deleted-banner` between the content-bar
and the scroll area. The sidebar 🗑️ folder icon comes from the existing `is_del` flag
in `/api/folders` (unchanged). Recently deleted notes appear in All Notes and search —
they are NOT excluded, only visually distinguished. Do not add "Recently Deleted" back
to `_SKIP_FOLDERS`; the warning banner is the correct signal for the user.

**Sync Report modal flow** — opens *at sync start* in live mode (× disabled); transitions
to re-index mode when export completes; transitions to report mode (full phase cards) when
done; then blocks on "Done — return to notes" button before calling loadFolders/loadTags/
loadNoteList. This ensures the user sees what changed before the list refreshes. Log button
in sidebar footer re-opens the report at any time. `window._syncLog` exposes the API:
`{openLive, updateLive, updateReindex, showReport, showError}`. The Done button's
`onclick` is set dynamically in the syncBtn handler for each sync run.

**Exporter is additive — we prune orphans** — `notes-export` has no clean/mirror
flag; replacing or removing a note's **non-image** attachment leaves the old file behind.
After every successful export `_prune_orphan_attachments()` scans every `(Attachments)/`
dir on disk, parses `href`/`src` attributes in the corresponding note HTML, and deletes
unreferenced **non-image** files. Three critical guards prevent false deletions:
(1) `_IMAGE_EXTS` — image files (`.png`, `.jpg`, `.jpeg`, `.gif`, `.heic`, `.heif`,
`.tiff`, `.tif`, `.bmp`, `.webp`, `.svg`, `.avif`) are NEVER deleted. The exporter
dual-writes images: base64 inline in the HTML AND a raw copy in `(Attachments)/`. The raw
copy is never referenced by path, so it would always appear orphaned without this guard.
(2) `if not referenced: continue` — if the HTML has zero path-references into the
`(Attachments)/` folder, skip it entirely. Either all content is base64 (nothing to clean)
or the HTML is a stale pre-rename copy (wrong match). (3) mtime guard — non-referenced
files newer than the HTML are skipped; the HTML predates them and cannot be authoritative.
Watermark used ONLY for the consistency gate (<75% notes present → abort). The gate
denominator is `pre_sync_count` (notes indexed before the export ran), NOT
`len(watermark_entries)`. The watermark is cumulative — exportedPath is never cleared
for deleted notes, so `len(entries)` grows over time and falsely triggers the gate on
healthy folders with accumulated deletions. `pre_sync_count` is captured from
`len(_state["notes"])` before the export starts and passed into `_prune_orphan_attachments`
as a parameter. Never revert to `len(entries)` as the denominator. Never remove the
three deletion guards — each one fixes a real false-deletion class.

---

## Persistence

`config.json` (gitignored) — Notes folder path only. `localStorage` — panel widths
(`notes-sidebar-w`, `notes-list-w`) and theme. Nothing else is written to disk.

## Never do

- Never call `_rebuild()` synchronously from a request handler — it holds `_lock`
  for the full index duration and starves other threads.
- Never set `active: True` only inside `build_index()` — the POST handler must set it
  first or the race condition returns.
- Never use `<embed type="application/pdf">` — always replace `<embed>`/`<object>`
  with `<iframe>`; `<embed>` renders blank in Safari.
- Never remove `/api/browse` from `_SETTINGS_PATHS` — the Settings folder picker
  silently breaks when `notes_root` is `None`.
- Never rewrite URLs or set `data-pdf-href` in a detached DOMParser document —
  Chrome's `innerHTML` serialiser decodes `%23` back to `#`, breaking PDF links in
  notes whose attachment folder contains a `#tag`.
- Never process inner `[data-pdf-href]` elements when replacing attachment cards —
  only the outermost; inner elements are guarded by `closest()`.
- Never hardcode the Sync filename scheme or weaken `_detect_export_prefix_args()`
  — Sync must match the existing folder's scheme (prefix vs none); a forced
  mismatch makes the incremental manifest duplicate the whole library.
- Never assume note loss when files vanish — the export is a derived artefact;
  Apple Notes is the source of truth. A `notes_root` inside a Syncthing/Dropbox/
  iCloud share will propagate cross-machine deletions in (looks like data loss,
  isn't). `_prune_orphan_attachments` aborts if <75% of watermark notes are on
  disk; never weaken that gate.
- Never commit `config.json` — it contains absolute local paths.
- Never increase the `sleep` in `Launch Notes.command` — the server starts async and
  shows a loading screen; sleeping longer does not fix slow startup.
- Never delete an HTML file without also removing its watermark entry from
  `AppleNotesExportSyncWatermark.json`. The incremental exporter skips any note whose
  watermark `modificationDate` matches Apple Notes — if the entry survives the delete,
  the exporter sees the note as "already exported, unchanged" and never rewrites it,
  leaving the viewer with a permanently missing note even though Apple Notes still has
  it. `POST /api/note/delete` removes the matching entry (keyed by `exportedPath`) as
  a best-effort step after unlinking the HTML. For notes that are genuinely gone from
  Apple Notes, removing the entry is harmless — the exporter simply skips them again.

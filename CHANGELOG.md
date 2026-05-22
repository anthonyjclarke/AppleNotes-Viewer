# Changelog

## [3.0.0] Unreleased

Major release — code-quality, performance, accessibility and documentation pass on
top of v2.7.0. No user-facing behaviour regressions; UX additions are explicitly
listed below. Internal architectural improvements summarised at the top of each
section.

### Added

- **Sort and attachment filter persist across reloads** — `sortMode` and
  `attachFilter` now stored in `localStorage` (`notes-sort`, `notes-attach-filter`).
  Open the app and your last-used sort/filter combination is restored.
- **`aria-pressed` on toggle buttons** — `searchAllPill`, `sortToggle`,
  `attachFilterPill`, theme toggle, and note-delete confirm buttons now announce
  their state to screen readers.
- **Force-close on stuck sync** — after 60 seconds with no live-output activity,
  the Sync Report modal's × button re-enables so the user can dismiss it without
  waiting for the 5-minute subprocess timeout.
- **API documentation** — new `docs/API.md` lists every HTTP endpoint with
  request/response shape, used for both human reference and a starting point
  for any future SDK or integration.
- **User test plan** — `docs/TEST_PLAN.md` covers the smoke tests for every
  release path, indexed for quick scan-down execution.

### Changed (internal — no user-visible behaviour change)

- **Capped HTML read during indexing** — `build_index()` now reads at most 64 KB
  per note (was unbounded). Title and `<meta name="modified">` are always within
  the first 1 KB; snippet caps at 280 chars; search index caps at 8 KB of body
  text. Peak indexing memory on a 1,800-note library with several 5 MB image
  notes drops from ~250 MB to ~40 MB transient.
- **Search corpus trimmed** — the per-note `_search` field is now derived from
  the capped body (≤ 8 KB) instead of the full body text. Resident memory after
  indexing drops by ~40% on real libraries with no measurable search-quality
  loss (substring matches concentrate near the top of notes).
- **Client index cached by version** — `/api/index-status` returns
  `index_version` (incremented on every `_rebuild()`). The client skips the
  `/api/notes` fetch when version is unchanged and the folder hasn't changed —
  eliminating 600 KB–1.5 MB JSON round-trips on every folder click.
- **De-duplicated `removeStaleFile` / `removeStalNote`** — collapsed into a
  single `removeNoteFromReport()` helper shared by both Sync Report cards.
- **De-duplicated "Deleted from Apple Notes" and "Stale HTML files" cards** —
  factored into `renderRemovableFileCard(label, intro, items)`. ~200 lines of
  duplicate template code removed.
- **`fmtSize`/`fmtBytes`/`_fmt_size` consolidated** — single `fmtSize()` helper
  on the client, single `_fmt_size()` on the server, with consistent precision
  rules (`X.Y MB` / `X KB` / `X B`).
- **Sync polling extracted** — `runSync()` was 130 lines mixing 5 phases. Now
  orchestrates four smaller phase helpers (`postSync`, `pollExportPhase`,
  `pollReindexPhase`, `pollFinalLogPhase`) via a shared `pollUntil()` utility.
- **Magic numbers named** — `_MAX_REFERENCED_HTML_SIZE`, `_GATE_THRESHOLD`,
  `_PREFIX_DETECT_THRESHOLD`, `_EXPORT_TIMEOUT_SEC`, `_LIVE_LINES_MAX`,
  `_LIVE_LINES_KEEP` replace inline numeric literals throughout `server.py`.

### Fixed

- **POST `/api/sync` race window** — the `active` check-then-set is now atomic
  inside one `with _lock` block. Two near-simultaneous clicks can no longer both
  pass the guard and start parallel exports.
- **`_wait_for_reindex()` infinite loop on stuck index** — added a 10-minute
  cap. If the index doesn't complete in that window, the wait thread exits and
  the partial log is marked complete with a warning, instead of leaking forever.
- **`fmtSize(0)` no longer renders "0 B"** — empty notes show a blank size badge
  instead of a literal zero.
- **Modal focus management** — opening About, Sync Report, or PDF preview now
  moves keyboard focus into the modal and traps Tab cycling inside until close.

### Documentation

- **CLAUDE.md split** — gotchas-only summary (≤ 120 lines) stays at
  `CLAUDE.md` per global guidance; deeper architectural notes moved into
  `docs/ARCHITECTURE.md`. Cross-linked.
- **Drift corrections** — `live_lines` "last 50" → "last 200"; "five server-side
  guards" → "six"; drift banner copy refers to the button rather than the
  command line; "Never do" list adds the empty-`<h1>` image guard.
- **README features list** — adds the Sync Log button and Force Full Re-export
  sidebar entry (both shipped in v2.6 but missing from the feature list).

---

## [2.7.0] 22-05-2026

### Fixed

- **Image-only notes not rendering** — notes whose sole content is an image (e.g.
  "Saved Photo" from the iPhone share sheet) are exported as
  `<h1><img src="data:image/jpeg;base64,…"></h1>`. The Step 4 `<h1>` suppression in
  `renderNote()` was hiding this element because `h1.textContent` is empty for image
  nodes. Fixed: the empty-text check now guards with
  `h1.querySelector("img, video, svg, canvas, object, embed")` before hiding — an
  `<h1>` that contains visual elements is preserved even if it has no text.

### Added

- **Stale-note drift detection** — after each incremental sync, the exporter's live
  Apple Notes count (`Incremental sync: N new/changed of M total`) is captured and
  compared against the re-indexed HTML count. If the folder contains more notes than
  Apple Notes reports (drift ≥ 10 notes or 2%, whichever is larger), a yellow warning
  banner appears in the Sync Report explaining that deleted notes may still be visible
  and showing the command to run a full re-export. Stored in `log["drift"]`; only fires
  for incremental syncs where the count line is emitted — benign no-ops and full exports
  are excluded.
- **Delete note from viewer** — hover any open note's date bar to reveal a 🗑 trash
  icon. Click → inline confirmation ("Remove from viewer only? / Cancel / Remove") →
  the HTML file and its `(Attachments)` folder are deleted from disk, the note is
  removed from the in-memory index immediately (no re-index), and the sidebar counts
  update. Auto-advances to the adjacent note. Five server-side guards prevent unsafe
  deletions: notes_root must be set, path must resolve within notes_root, depth must
  be exactly 3, file must be `.html`, file must exist. Does not touch Apple Notes —
  if the note still exists there, the next ↻ Sync will restore it.
- **Force Full Re-export — in-app `--reset-sync` with stale-file detection** —
  new ⟲ button in the sidebar footer (and inside the drift warning banner) runs
  `notes-export export --format html --incremental --reset-sync --verbose` after a
  confirmation dialog. This is the only reliable way to relocate notes that have moved
  to Recently Deleted in Apple Notes — the incremental exporter cannot detect Apple-
  Notes-internal folder moves because the note's `modificationDate` does not change.
  After the export completes, `_detect_stale_html_files()` scans the fresh watermark
  (which now contains only entries for notes currently in Apple Notes) against on-disk
  HTML files at depth 3 and identifies every file that no longer matches a live note.
  These are surfaced in a new **"Stale HTML files on disk"** card in the Sync Report
  with individual **Remove** and bulk **Remove all** buttons (sharing the same row UI
  and `removeStaleFile` helper as the existing "Deleted from Apple Notes" card). The
  Sync Report header shows "⟲ Forced full re-export" instead of "Incremental sync"
  for these runs. `POST /api/sync` now accepts `{"reset_sync": true}`; the body field
  flows through to `_run_export_async(notes_root, bin_path, reset_sync=True)` which
  conditionally appends `--reset-sync` to the exporter command. `log["reset_sync"]`
  and `log["stale_files"]` are added to the structured sync log.
- **Recently Deleted notes visible and flagged** — notes in Apple Notes' Recently Deleted
  folder are now indexed and visible everywhere (note list, All Notes, search). They are
  distinguished by a red `🗑 Recently Deleted` pill badge in the note list, a muted title
  colour, a red active-selection indicator, and a red warning banner at the top of the
  content pane: *"This note has been deleted from Apple Notes and will be permanently
  removed within 30 days. It can still be restored from Recently Deleted in Apple Notes."*
  `_SKIP_FOLDERS` is now an empty set; `_RECENTLY_DELETED_FOLDERS` (lowercase) covers
  `recently deleted`, `trash`, and `deleted items`. The `recently_deleted: bool` field
  is included in the client-facing note index so both list and content rendering can
  branch on it without extra API calls. The sidebar 🗑️ folder icon (already present via
  the `deleted` flag in `/api/folders`) now appears correctly because the folder is
  populated.
- **Delete note — watermark entry removed on delete** — `POST /api/note/delete` now
  removes the deleted note's entry from `AppleNotesExportSyncWatermark.json` after
  unlinking the HTML file. Without this, the incremental exporter sees the note as
  "already exported, unchanged" (watermark `modificationDate` matches Apple Notes) and
  permanently skips re-exporting it, so a note deleted from the viewer but still present
  in Apple Notes would never reappear after ↻ Sync. Removing the entry makes the next
  sync treat the note as brand-new. For notes genuinely gone from Apple Notes the
  removal is harmless — the exporter simply skips them again. Best-effort: a watermark
  read/write failure does not fail the delete response.
- **Attachment cleanup consistency gate fix** — the gate previously compared present
  on-disk files against `len(watermark_entries)` (all notes ever exported, cumulative).
  Since `exportedPath` is never cleared for deleted notes, this count grows indefinitely
  and eventually falls below the 75% threshold on healthy folders with many accumulated
  deletions, blocking cleanup. Fixed: gate now uses `pre_sync_count` (notes indexed
  immediately before the export ran, captured from `len(_state["notes"])`). This stays
  stable regardless of watermark history and only triggers when files actually disappear
  between syncs (cloud-sync disruption, interrupted export).
- **Deleted-from-Apple-Notes detection in Sync Report** — `apple-notes-exporter
  --verbose` emits `Deleted (no longer in Notes): <path>` lines for notes previously
  exported but since deleted from Apple Notes. The exporter updates its watermark but
  leaves the HTML on disk. These lines are now parsed during the stderr loop
  (`_DELETED_NOTE_RE`), deduplicated, and stored in `log["export"]["deleted_notes"]`.
  The Sync Report renders a **"Deleted from Apple Notes"** phase card listing each file
  with individual **Remove** and bulk **Remove all** buttons — both call
  `POST /api/note/delete`. The card is complementary to the count-based drift banner:
  `deleted_notes` provides exact confirmed paths from this sync's output; the drift
  banner catches accumulated old deletions beyond that list.
- **Note file size indicator** — HTML file size is now indexed (`"size": bytes`) and
  shown in every note list item as a compact badge (e.g. `340 KB`, `1.2 MB`) in the
  title row alongside the date. Colour-coded by tier: `< 100 KB` near-invisible, `100
  KB–1 MB` secondary, `≥ 1 MB` amber `#FF9500`, `≥ 5 MB` red `#FF3B30`. HTML size
  is the authoritative proxy for total note weight (inline base64 images are included).
  A **↓ Date / ↓ Size** sort toggle in the list-panel meta row lets users sort by
  largest-first; the date group headers switch to size-bucket headers (`5 MB and
  above`, `1 – 5 MB`, `100 KB – 1 MB`, `Under 100 KB`) while size sort is active.
- **Attachment indicator and sidebar filter** — `build_index()` checks for a
  `{stem} (Attachments)/` directory alongside each HTML file and stores
  `"has_attachments": bool`. Notes with attachments show a small paperclip SVG icon
  in the title row. A **Has Attachments** filter pill in a new Filters section at the
  bottom of the sidebar (above Tags) toggles client-side filtering; the note count
  updates to `N notes with attachments` and the empty-state message is context-aware.
  The filter persists across folder and tag changes and ANDs with any active search.
- **Settings Back button** — when a notes folder is already configured, a `← Back`
  button appears alongside the `Save & Index Notes` button in a flex row. Clicking
  it returns to the viewer (`window.location.href = '/'`) without triggering
  re-indexing. Hidden on first run (no path configured, nowhere to go back to).

### To Do

- **sync.sh scheme parity** — port `_detect_export_prefix_args()` logic to bash so
  standalone `bash sync.sh` also auto-detects the date-prefix scheme, matching the
  in-app Sync button. Currently only the server-side Sync auto-matches.
- **Pipe tables → HTML tables** — parse pipe-delimited markdown tables inside
  `exporter-prose` blocks and render them as proper `<table>` elements using the app's
  existing styled table CSS (striped rows, borders, rounded corners). Currently rendered
  as monospace fixed-width text.
- **System font** — switch the app's base font to `-apple-system, "SF Pro Text",
  sans-serif` to match Apple Notes' native macOS typeface. Low effort, noticeable
  authenticity improvement.
- **Horizontal rules** — `---` on its own line inside exporter blocks should be
  converted to a `<hr>` element, matching Apple Notes' divider style.
- **Search highlight in content pane** — when a search is active, highlight matching
  terms in the note body as well as the note list snippets.

---

## [2.5.0] 20-05-2026

This is a milestone release. The sync, cleanup, and reporting feature set introduced
across v2.4.x is now complete and production-tested against a real library of 1,688
notes. No data loss was observed across repeated sync cycles. All three orphan-cleanup
guards held correctly in live testing.

### Added

- **`APP_VERSION` constant in `server.py`** — version is now defined in one place and
  returned by `/api/index-status` as `{"version": "2.5.0", ...}`. Previously version
  appeared only as a hardcoded string in `app.html`.
- **About panel reads version dynamically** — `init()` fetches version from
  `/api/index-status` on startup and updates the About panel. The hardcoded `v2.4.4`
  string that had been stale since May is replaced. Future version bumps only require
  updating `APP_VERSION` in `server.py`.

### Fixed

- **"Starting sync" text persisted through Re-indexing and completed Sync Report** —
  `syncLogLiveMeta` was set to "Starting sync…" when the modal opened and never cleared
  as the sync progressed. It is now hidden when the re-indexing phase begins
  (`updateReindex`) and again in `showReport()`, so neither the Re-indexing title nor
  the completed report shows a stale transient status below it. Restored by `openLive()`
  at the start of each new sync.

### Testing

Full test run against a 1,688-note iCloud export (1,674 dated notes + 414 epoch-date
notes + 8 `Unknown Folder` notes):

- Two successive syncs with no note changes — zero files removed on both passes
- One sync with 9 changed notes — exactly one genuine orphan PDF correctly removed
- All images preserved across all three runs (`_IMAGE_EXTS` guard confirmed working)
- Benign no-op exit from `notes-export` handled cleanly (no false "Sync failed")
- Log button, resizable modal, and PDF inline viewer all verified

---

## [2.4.9] 20-05-2026

### Fixed

- **Attachment cleanup wrongly deleted current image files on every sync** — a
  fundamental design flaw in `_prune_orphan_attachments`. Three compounding causes:

  **1. Exporter dual-writes images.** For every image attachment, `notes-export`
  embeds the image as base64 (`<img src="data:image/png;base64,…">`) in the HTML AND
  copies the raw file to the `(Attachments)` folder. The HTML never references the raw
  file by path. Our cleanup read the HTML, found no `href`/`src` pointing to the file,
  and concluded it was an orphan — deleting it on every sync, only for the exporter to
  recreate it on the next. Fixed with `_IMAGE_EXTS`: files with image extensions
  (`.png`, `.jpg`, `.jpeg`, `.gif`, `.heic`, `.heif`, `.tiff`, `.tif`, `.bmp`,
  `.webp`, `.svg`, `.avif`) are now unconditionally skipped. The exporter's raw image
  copies are never touched.

  **2. Stale HTML stem-mismatch.** When a note title changes (e.g. `Pathology Report`
  → `Pathology Report #health`), the exporter writes a new HTML file under the new
  name but leaves the old `Pathology Report.html` on disk. Our cleanup matched the
  `Pathology Report (Attachments)` folder to the old stale HTML by stem. The stale
  HTML did not reference the new PDFs in the folder, so they appeared orphaned. Fixed
  by skipping a folder entirely when the matched HTML has zero path-references into it
  (`if not referenced: continue`): if the HTML doesn't reference a single file in the
  folder by path, it is either all-base64 or the wrong HTML — nothing is safe to delete.

  **3. Files newer than the HTML.** If any candidate file in an `(Attachments)` folder
  was created or modified *after* the HTML was written, the HTML predates the file and
  cannot possibly reference it. Deleting it would be wrong. Fixed by skipping
  non-referenced files whose `mtime` is newer than the HTML's `mtime`.

  Together these three guards make cleanup conservative: only non-image files, in
  folders the HTML actively references, whose files are older than the HTML, are
  considered orphans. PDFs removed from a note are still cleaned up correctly.

---

## [2.4.8] 20-05-2026

### Fixed

- **Attachment files wrongly deleted for notes with `&` in the title** — the most
  serious bug in the orphan cleanup. When a note title contains `&` (e.g. "Mum & Dad"),
  the exporter HTML-encodes the attachment path in `href`/`src` attributes as
  `Mum &amp; Dad (Attachments)/file.png`. `_referenced_attachments` tried the raw value
  and the URL-decoded value, but neither affected `&amp;`. The resolved path didn't match
  the actual folder `Mum & Dad (Attachments)/`, so the file appeared unreferenced and was
  deleted. Fixed by also trying `html_unescape(raw)` and `html_unescape(unquote(raw))` as
  candidate paths. Any note title with `&`, `'`, `"`, or other HTML-special characters is
  now handled correctly.

- **"Sync error" shown at end of every sync** — `showReport()` called
  `document.getElementById("syncLogLiveLabel").textContent = …` but the element had no
  `id` attribute, so `getElementById` returned `null` and setting `.textContent` threw a
  `TypeError`. The outer `catch` in the syncBtn handler caught it and showed "Sync error"
  even though the sync had completed successfully. Fixed by adding `id="syncLogLiveLabel"`
  to the div.

- **Log button did nothing** — the same `TypeError` above propagated out of `showReport`
  inside `openReport()`; the silent `catch {}` swallowed it, so `overlay.classList.add
  ("open")` never ran and the modal never appeared. Fixed by the same `id` addition.

- **Live output pane scroll leaked to outer modal** — when scrolling the live pre to its
  boundary, the browser passed the event to the outer `.synclog-modal` container, making
  it feel impossible to scroll all the way to the top. Fixed with `overscroll-behavior:
  contain` on `.synclog-pre`.

### Added / Changed

- **Live output pane is always dark** — the dark terminal style (`#1c1c1e` background,
  `#d4d4d4` text) is now applied during both the live streaming phase and the post-sync
  review phase; previously it only applied in review mode.

- **Sync log: date/time header and exporter annotation** — the terminal log now opens
  with three header lines before any exporter output:
  ```
  ── Sync started 19 May 2026 at 8:31 pm ──
  Type: Incremental  ·  Scheme: Date-prefixed filenames (YYYY-MM-DD)
  ── Exporter output ──
    (✓ = note exported  ·  [N/M] = exporter progress counter: N of M notes done)
  ```
  `[N/M]` progress counter lines are merged onto the preceding `✓ Exported:` line
  (e.g. `✓ Exported: App  [1/7]`) and deduplicated when the exporter emits the same
  counter twice, eliminating confusing bare counter lines.

- **Log button shows terminal log only** — reopening via the sidebar **Log** button now
  shows only the scrollable terminal pane (no phase cards, no Done button). Close with
  the × button or Escape.

- **Resizable sync report modal** — drag the bottom-right corner handle to resize the
  modal; minimum 420 × 260 px, maximum near-fullscreen. Default width widened from
  560 px to 640 px. Scrolls on both axes if content overflows.

- **Live tail extended** — `GET /api/sync` now returns the last 200 stderr lines
  (was 50) for the live output pane during a running sync.

---

## [2.4.7] 19-05-2026

### Fixed

- **Sync no longer fails when there is nothing to export** — `notes-export` exits
  with a non-zero code when the library is already up to date ("All notes are up to
  date, nothing to export."). The export phase treated any non-zero exit as a failure,
  so an unchanged library showed **Sync failed × ERROR** even though the exporter ran
  perfectly. The export phase now recognises the benign no-op messages ("nothing to
  export", "all notes are up to date", "no notes to export", "no changes") and treats
  them as success, normalising the recorded exit code to 0 so the report shows a
  clean run. Real failures (other non-zero exits) still error as before.

### Added

- **Detailed, scrollable cleanup log** — the attachment cleanup phase now streams
  exactly what it does into the live output, line by line:
  - `── Attachment cleanup ──` header
  - `Scanning (Attachments) folders for orphaned files…`
  - `  ✗ orphan removed: <note> / <file> (<size>)` per deleted file
  - `  ✗ empty folder removed: <folder>` per removed empty directory
  - `  ! could not remove <file>: <error>` if a deletion fails
  - `Scanned N folders.` and a `✓ Cleanup:` summary line
  - the consistency-gate skip reason (with a ⚠ prefix) when cleanup is skipped

- **Full combined sync log** — `log["full_log"]` now captures the entire run —
  exporter stderr **and** cleanup actions — as one continuous stream. The Sync
  Report's top pane shows this as a **terminal-style review window**: dark
  background, monospace, tall (up to 52 vh), scrollable up and down so the whole
  sync can be reviewed at leisure. The pane label reads "Full sync log — N lines
  (scroll to review)". Re-opening via the **Log** button shows the identical view.

- `_emit_sync_line()` — thread-safe helper that appends one line to the live sync
  buffer (used by cleanup); `_fmt_size()` — human-readable byte sizes for log lines.

---

## [2.4.6] 19-05-2026

### Fixed

- **Empty `(Attachments)` folders no longer clutter Finder** — `notes-export` creates
  `(Attachments)` subdirectories for notes and touches them on every incremental run,
  even if a note has no attachments. This caused all attachment folders to show "Today"
  as their modified date in Finder after every sync, making it appear as if the export
  had changed when nothing had.

  `_prune_orphan_attachments` now removes any `(Attachments)` folder that is empty
  after the orphan-file pass (either it was already empty, or all its files were
  orphans and just deleted). The exporter will recreate the folder if the note is
  re-synced with attachments in future.

  The Sync Report modal **Attachment cleanup** card now shows empty folders removed
  separately from orphaned files (e.g. "2 orphaned files removed — 1.4 MB freed ·
  47 empty folders removed"), and the no-op message was updated to "No orphaned
  attachment files or empty folders".

  `dirs_removed` added to the cleanup result dict and to the log's `cleanup` section.

---

## [2.4.5] 19-05-2026

### Fixed

- **Empty sync report after re-index (race condition)** — the report modal showed
  "0 notes indexed", "0 output lines", and zero timings when the client fetched
  `/api/sync-log` before `_wait_for_reindex` had finished writing the final log.

  Fixed with two coordinated changes:

  *Server:* a partial log (`log_complete: false`) is written to `_state["sync_log"]`
  immediately before `_start_rebuild_async()` is called, so the client always has
  export and cleanup data even if it polls mid-rebuild. `_wait_for_reindex` then
  sets `log_complete: true` after the index finishes, reducing its polling interval
  from 0.5 s to 0.2 s to minimise the delay between index completion and the flag.

  *Client:* the sync handler now polls `/api/sync-log` in a 300 ms loop (instead of
  a single immediate fetch) and waits until `log_complete === true` before rendering
  the report — guaranteeing the note count, re-index duration, and total elapsed time
  are all populated.

- **Sequential log view** — the Sync Report modal now keeps the live exporter output
  visible above the phase cards when transitioning from the live phase to the report
  phase (`showReport` called with `keepLive=true`). Previously the live section was
  hidden and the output was only available via the collapsible "Exporter output"
  details element, making it feel disconnected from the report. Now the full captured
  output scrolls back to the top and the structured phase cards appear directly below,
  reading as one continuous sequential log of the sync run. The now-redundant
  collapsible raw output section is suppressed in this view.

---

## [2.4.4] 19-05-2026

### Fixed

- **Orphan attachment cleanup missed removed attachments** — when a PDF or image was
  deleted from a note in Apple Notes and the note was re-synced, the old file was not
  removed from the `(Attachments)/` folder. Root cause: `_prune_orphan_attachments`
  relied on the watermark's `attachmentPaths` field to determine which files were
  still expected — but the exporter does NOT clear that field when an attachment is
  removed; it only ever adds to it. The old path remained in `attachmentPaths`, so the
  cleanup treated the file as "expected" and skipped it.

  Fixed by switching orphan detection from watermark-based to **HTML-parsing-based**:
  instead of trusting `attachmentPaths`, the function now scans every `(Attachments)/`
  directory on disk, parses `href` and `src` attributes in the corresponding note HTML
  (the re-exported, current version), and deletes any file the HTML no longer references.
  The watermark is still used for the consistency gate but no longer drives per-file
  detection. This correctly handles removing one attachment (others remain), removing all
  attachments, and replacing an image.

  Fail-safes preserved: no corresponding HTML → skip that folder; HTML > 10 MB (large
  inline base64 images) → skip; only regular files directly inside `(Attachments)/` ever
  deleted.

- **`notes-export --verbose` format confirmed from live output** — the exporter emits
  `✓ Exported: <title> [done/total]` per note and a header line `Incremental sync: N
  new/changed of M total`. Previously treated as unverified freeform.

---

## [2.4.3] 19-05-2026

### Added

- **Live Sync Report modal** — the Sync Report modal opens *immediately* when ↻ Sync
  is clicked and shows the sync running in real time; transitions to a full structured
  report when complete, then pauses for user confirmation before refreshing the note
  list. Also re-openable at any time via the **Log** button in the sidebar footer.

  **Live phase** (while running):
  - Title "Syncing…" with a pulsing ● Live badge
  - Progress bar and status line — % and count for full export, honest indeterminate
    for incremental
  - Scrolling **Live output** pane streaming the last 50 lines of `notes-export`
    verbose stderr in real time, auto-scrolled to the most recent line
  - × close button disabled while syncing — user cannot accidentally dismiss mid-run

  **Re-index phase**: title transitions to "Re-indexing…" with live count progress

  **Report phase** (when complete):
  - ✓ Done badge replaces ● Live
  - Three phase cards with status icons and timings:
    - **Export** — Full/Incremental, filename scheme, exporter output line count
    - **Attachment cleanup** — per-file table (Note · Filename · Size) with bytes
      freed, "No orphaned files", or ⚠ warning if consistency gate tripped
    - **Re-index** — notes indexed and duration
  - **Total elapsed time** across all phases
  - Collapsible **Exporter output** — full raw stderr, last 500 lines, scrollable
  - **Done — return to notes** button — user explicitly confirms; only then does the
    note list refresh (loadFolders / loadTags / loadNoteList)

- **`GET /api/sync`** now returns `live_lines` — last 50 stderr lines from the running
  export for the modal's live output pane (server caps accumulation at 1000 lines)
- **`GET /api/sync-log`** — structured log dict for the last completed sync
- **`_prune_orphan_attachments` returns rich dict** — previously `(int, int)`;
  now `{files_removed, bytes_freed, items:[{note,file,size}], skipped, skip_reason}`
- **`import time`** added to `server.py` for `time.monotonic()` phase timing

---

## [2.4.2] 18-05-2026

### Added

- **Sync auto-matches the existing filename scheme** — the app's ↻ Sync ran the
  no-prefix exporter default, so if the initial export was date-prefixed
  (`YYYY-MM-DD Title.html` — e.g. the GUI app with the date option on), the
  incremental manifest mismatched and every note silently duplicated. Sync now
  detects the existing scheme — from the watermark's `exportedPath`s, falling
  back to a scan of on-disk note files — and appends `--add-date-prefix
  --date-format iso` when ≥ 80% are date-prefixed, so it writes the *same*
  filenames the manifest expects and updates in place. Empty/unknown folder →
  no prefix (unchanged default). This removes the prefix/no-prefix footgun
  regardless of how the initial export was produced.

- **Cleanup consistency gate (data-safety guard)** — `_prune_orphan_attachments`
  now refuses to run if fewer than 75% of the watermark's notes are present on
  disk. This protects against compounding damage when the export folder is in a
  broken/partial state — interrupted export, manual deletion, or (the real-world
  trigger) a cloud-sync tool such as **Syncthing/Dropbox/iCloud Drive**
  propagating deletions into the folder. When tripped it skips all deletion and
  surfaces an explanatory status. Investigation note: a reported "database
  destroyed" (≈1,632 of 1,684 notes vanished) was traced to Syncthing
  replicating cross-machine deletions into a `notes_root` that lived inside a
  Syncthing share — **not** the exporter or this app. A dry-run of the prune
  against that folder confirmed it would have deleted 0 files; it structurally
  only touches files inside `* (Attachments)/` folders, never note HTML. No real
  notes were lost — the export folder is a derived artefact; Apple Notes remained
  the intact source of truth. See README "Do not use a cloud-synced folder".

- **Orphaned attachment cleanup on sync** — `notes-export` is additive at the file
  level: editing a note to shrink/replace an embedded image re-exports the note and
  writes the *new* attachment but never deletes the *old* one (e.g. an original
  `Pasted Graphic 2.tiff` lingers beside a new `CleanShot ….png`), so attachment
  folders bloat over time. There is no exporter prune/clean/mirror flag. After every
  successful export the app now sweeps each note's `(Attachments)/` folder against
  the freshly-written `AppleNotesExportSyncWatermark.json` and removes any file the
  note no longer references. Strictly fail-safe: no/unreadable watermark, a folder
  with no matching watermark entry, or attachment paths that don't resolve into the
  folder → that folder is left untouched; only regular files directly inside a
  `* (Attachments)` folder are ever deleted (note HTML and nested dirs never).
  Also cleans attachments for notes that lost all images or were deleted. The count
  of removed files is surfaced in the sync footer status.

### Changed

- **Sync progress is now legible and honest** — the footer previously showed a
  bare incrementing count ("Exported 779…") with no total and no bar, because
  the server never populated `sync_progress.total`. Critically, that count is
  the number of non-empty **stderr lines** from `notes-export --verbose`, *not*
  a note count — the exporter's stderr is freeform (docs only promise "progress
  and errors go to stderr") and emits more than one line per note, so the figure
  climbs **past the real note count** ("Exporting 1992 · 1683]" on a smaller
  library). The `1683]` token was a parsed fragment of an unverified verbose
  line. Now:
  - **Full export** (no watermark) — the server fetches the real note count via
    `notes-export list-notes` and sets `total`. The footer shows a true
    **percentage bar**, with the line-count **clamped to the total** so it can
    never display more than exist: `Exporting notes — 72% (1916 / 2655)…`.
    Best-effort: any failure (no Full Disk Access, timeout) falls back to the
    indeterminate indicator below.
  - **Incremental sync** — the changed-note count is unknowable up front and the
    stderr count is unreliable, so the footer shows an **animated indeterminate
    sweep bar** with honest text ("Syncing — exporting changed notes…") and
    **no fabricated number or parsed note name**.
  - Removed the `friendlyCurrent()` stderr-line parser entirely — it produced
    meaningless tokens from an unverified format. The trustworthy
    orphan-cleanup status (a string the server itself sets) is still surfaced.
  - The re-index phase reuses the same bar (`Re-indexing N / Total…`) for a
    continuous two-phase progression, and the bar resets cleanly on completion
    or error. Replaced the opacity `sync-pulse` text flash with the shared
    `scan-sweep` bar animation already used by the startup overlay.

### Documentation

- **Export usage clarified** — README now instructs `--incremental` from the *first*
  export (full export + writes the manifest in one pass; omitting it forces a wasteful
  second full export later). Fixed the "Force a full re-export" command, which was
  missing `--incremental` (`--reset-sync` is only effective alongside it).
- **Filename scheme warning** — documented that the exporter defaults to *no* date
  prefix while `--add-date-prefix` adds the creation date, and that mixing the two
  schemes across export/sync silently duplicates every note (the incremental manifest
  keys on the exported path). README, CLAUDE.md, and the integration doc now state the
  rule: pick one scheme and use it for every export and sync. Folder-structure example
  updated to the actual no-prefix default.
- **Dates & times explained** — new README section documents that sort order comes
  from `<meta name="modified">` (mtime fallback), the `YYYY-MM-DD ` filename prefix is
  cosmetic and never used for dates (answering the prior "why is the app stripping the
  date prefix?" question), and the "1 Jan 2001" cluster reflects Apple Notes' own
  missing metadata, not a bug.
- The duplication issue itself needed no code change — the Sync command already
  used the correct no-prefix default; it was undocumented usage, not a defect.

---

## [2.4.1] 17-05-2026

### Fixed

- **Sync crash on POST `/api/sync`** — `NameError: name 'state' is not defined` caused
  the sync endpoint to return a 500 and the browser to show "Failed to fetch". Fixed
  typo: `state.get("notes_root")` → `_state.get("notes_root")`.
- **Version strings** — About modal, README, and CLAUDE.md now consistently show the
  current version.

---

## [2.4.0] 17-05-2026

### Added

- **Sync progress feedback** — sync is now fully non-blocking. POST `/api/sync` returns
  immediately; the export runs in a background thread via `subprocess.Popen`, streaming
  `notes-export --verbose` stderr line-by-line. A new `sync_progress` key in `_state`
  tracks `{active, done, total, current, error}`. The sync button updates live
  (`↻ 42` while exporting, then hands off to the existing index-progress poll); the
  status label shows "Exported N…" during export and "Scanning / Indexing X / Y" during
  re-indexing.
- **`notes-export` binary auto-discovery** — Finder and launchd strip `PATH` to a
  minimal set, causing `notes-export` not found errors when launching via
  `Launch Notes.command`. `server.py` now provides `_find_notes_export_bin()` which
  probes five known locations including the app bundle at
  `/Applications/Apple Notes Exporter.app/Contents/SharedSupport/notes-export`.
  `sync.sh` applies the same ordered probe before invoking the binary.

### Fixed

- **Preview pane width cap** — removed the 740 px `max-width` constraint on `.note-body`
  so wide content (monospace tables, long `<pre>` blocks) fills the content panel.
  `word-break: break-word` is now scoped to prose elements only (`p`, `li`, headings),
  preserving fixed-width column alignment in monospace tables.
- **Exporter-fragmented `<pre>` rendering** — `apple-notes-exporter` wraps every text
  segment between bold markers in its own `<pre style='background:#f5f5f5'>`, producing
  one grey monospace box per word or phrase. `renderNote()` Step 5 now collapses
  consecutive runs: strips `**` delimiters (`<b>**text**</b>` → `<strong>`), converts
  `##`/`###` prefixes to `<h2>`/`<h3>` headings, collects pipe-table rows into a
  `<pre class="exporter-table">` block, and converts `- item` lines to `<ul><li>`
  elements. The result is rendered as a single monospace block matching the intent of
  the original Apple Notes content.

---

## [2.3.0] 16-05-2026

### Added

- **Windows support** — `Launch Notes.bat` double-click launcher for Windows; kills any
  existing server on port 8765, starts Python server backgrounded in the same console
  window (closing the window stops the server), waits 2 s, then opens the browser.
  Includes a Python availability check with a clear install message if Python is missing.
- **Windows-aware Settings page** — path placeholder and hint text are now OS-specific;
  Windows users see a Windows-style path example and an Explorer address-bar tip instead
  of the macOS Finder/Terminal instructions.
- **Windows sync error message** — clicking ↻ Sync on Windows returns a clear message
  explaining that export requires macOS and describing the manual copy workflow, rather
  than silently failing or attempting to run `sync.sh`.
- **README platform sections** — README rewritten with dedicated macOS and Windows
  quick-start sections, platform support table, and Windows-specific notes-update workflow.

---

## [2.2.0] 16-05-2026

### Added

- **About modal** — new "i" info button in the sidebar header opens an About panel
  with version, how-to-use steps, GitHub and BlueSky links, and attribution to
  `apple-notes-exporter` by Konstantin Zaremski.
- **PDF attachments rendered inline** — PDF attachment cards produced by
  `apple-notes-exporter` (the styled flex-card structure) are now replaced with inline
  `<iframe>` elements directly in the note body, showing the PDF without needing to
  click a modal. `<embed>` and `<object>` elements are likewise replaced with
  `<iframe>` (not just src-rewritten), so PDF content displays in both Safari and Chrome.

### Fixed

- **Hashtag `<h1>` clutter** — `apple-notes-exporter` splits note titles containing
  `#tags` into one `<h1>` element per token (e.g. `<h1>Meeting </h1><h1>#work</h1>`).
  The viewer now hides any `<h1>` after the first whose content is solely `#hashtag`
  tokens, eliminating the duplicate heading and orphaned tag fragment.
- **Sync footer visual feedback** — the sync footer now enters a visible "syncing"
  state: yellow-tinted background, pulsing status label, and a yellow-filled sync
  button. Status text is more granular: "Exporting notes…" during the sync.sh phase,
  "Scanning…" during the indeterminate rglob phase, and "Indexing X / Y…" once the
  total is known.
- **`<iframe>` styling** — inline `<iframe>` elements (PDF embeds) now share the same
  bordered, rounded-corner box style as `<embed>`/`<object>` in the note body.

---

## [2.1.0] 12-05-2026

### Fixed

- **Tag extraction** — tags now match Apple Notes exactly:
  - Digit-first tags (`#10SmallSt`, `#60thBigBash`) are now detected; the previous
    regex required a letter as the first character
  - Two-character tags (`#AI`) are now detected; the previous minimum was three characters
  - Tags embedded by `apple-notes-exporter` in the HTML filename are extracted as the
    authoritative source (`stem_tags`); body text tags still extracted as a secondary source
  - Threshold: filename-sourced tags shown if they appear in ≥ 1 note; body-only tags
    require ≥ 2 notes (noise filter unchanged)
- **PDF inline viewer** — switched the modal embed from `<embed type="application/pdf">`
  to `<iframe>` so PDFs render reliably in Safari and Chrome via the browsers' native viewer
- **Settings browse button** — the folder picker was silently broken whenever
  `notes_root` was `None` (first run or stale config): the first-run redirect guard was
  blocking `/api/browse`; it is now explicitly allowed through
- **Stale config path shown in Settings** — when the configured Notes folder does not
  exist on the current machine (e.g. a path from a different Mac), the Settings page
  now pre-fills the path field with the old value so it can be corrected, rather than
  showing an empty field
- **Indexing progress — scan phase** — before the total note count is known, both the
  Settings page and the startup overlay now show an animated indeterminate sweep bar
  with label "Scanning notes folder…" instead of "0 / 0 notes indexed…"
- **PDF click in notes with `#` in attachment path** — notes where the attachment
  folder name contained a `#tag` (e.g. `2019-12-23 Dermatologist #health
  (Attachments)/…`) caused the PDF to open in the same browser tab instead of the
  inline modal. Root cause: URL rewriting was done in a detached DOMParser document
  and the resulting `innerHTML` was serialised/re-parsed into the live DOM; Chrome's
  HTML serialiser can decode percent-encoded characters in URL attributes during that
  round-trip, corrupting the `/static/…` href before `data-pdf-href` could be set.
  Fixed by moving all URL rewriting and `data-pdf-href` marking to execute directly
  on the live DOM elements (after `noteBody.innerHTML` is planted), eliminating the
  serialisation round-trip entirely. A belt-and-suspenders fallback in the click
  listener also now intercepts any `<a href="….pdf">` that was missed by the primary
  marking pass.

---

## [2.0.0] 11-05-2026

Complete rewrite. The app is now built around the
[`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter) CLI
instead of Falcon Notes Exporter. The Notes folder is user-selectable via the in-app
Settings page — no manual file placement required.

### Added

- Settings page with file-browser overlay for selecting the Notes export folder
- Startup loading overlay with progress bar — server is immediately available while
  indexing runs in a background thread
- Sync button in sidebar — runs `apple-notes-exporter --incremental` then re-indexes
  without restarting the server; progress tracked live
- PDF preview modal — inline viewer with "Open in new tab" fallback; triggered by
  clicking anywhere on an attachment card (filename, icon, or type label)
- Resizable sidebar panel (folders + tags); width persists in `localStorage`
- Tag pills grid replacing the previous list-style tag display, matching Apple Notes style
- `sync.sh` — configurable sync wrapper around `apple-notes-exporter`
- `<meta name="modified">` parsing as primary date source; mtime as fallback

### Changed

- Notes folder is now configured via the Settings UI rather than manually placed in
  `Notes/` — path stored in `config.json` (gitignored)
- Startup is now asynchronous — HTTP server binds immediately, browser opens to a
  loading screen while indexing completes in the background
- Tag display redesigned from a list (with `#` icon prefix) to a wrapping pill grid
- Both the sidebar↔list and list↔content dividers are now draggable resize handles

### Fixed

- `#` in folder or file names caused 404 errors — fixed by per-segment URL encoding
  so `#` becomes `%23`, not a URL fragment
- Settings save race condition: index progress `active` flag is now set in the POST
  handler before the background thread starts, preventing premature redirect with old data
- PDF attachment card: clicking the emoji icon or "Scan File" label (siblings of the
  `<a>` element) now correctly opens the modal; the outer card div is also marked
  with `data-pdf-href` during rewriting

---

## [1.0.0] 09-05-2026

Initial release.

### Added

- Local web viewer for Apple Notes exports from Falcon Notes Exporter
- Three-column layout mirroring Apple Notes desktop: sidebar, note list, content pane
- Full-text search with highlighted matches; results as you type
- `#hashtag` detection and tag sidebar (list style)
- Last-edited sort order via mtime set by Falcon Notes Exporter
- Light/dark mode toggle; preference persists in `localStorage`
- Image lightbox
- Resizable note list ↔ content divider; width persists in `localStorage`
- Keyboard shortcuts: `/` or `⌘F` to focus search, `↑`/`↓` to navigate, `Escape` to clear

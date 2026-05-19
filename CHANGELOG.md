# Changelog

## [Unreleased]

### To Do

- **sync.sh scheme parity** — port `_detect_export_prefix_args()` logic to bash so
  standalone `bash sync.sh` also auto-detects the date-prefix scheme, matching the
  in-app Sync button. Currently only the server-side Sync auto-matches.
- **Sync progress** — verify verbose output format from `notes-export --verbose` once
  Full Disk Access is granted to Terminal; confirm per-note stderr line count matches
  `done` counter in `sync_progress` state.
- **Pipe tables → HTML tables** — parse pipe-delimited markdown tables inside
  `exporter-prose` blocks and render them as proper `<table>` elements using the app's
  existing styled table CSS (striped rows, borders, rounded corners). Currently rendered
  as monospace fixed-width text.
- **Literal `**bold**` cleanup** — some exporter output uses raw `**text**` in plain
  text nodes rather than `<b>**text**</b>` tags (e.g. `**Colour key:**` footer lines).
  A second regex pass over text nodes inside `.exporter-prose` would strip these
  remaining `**` markers and apply `<strong>` styling.
- **System font** — switch the app's base font to `-apple-system, "SF Pro Text",
  sans-serif` to match Apple Notes' native macOS typeface. Low effort, noticeable
  authenticity improvement.
- **Horizontal rules** — `---` on its own line inside exporter blocks should be
  converted to a `<hr>` element, matching Apple Notes' divider style.
- when searching highlight the search in the preview pane as well

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

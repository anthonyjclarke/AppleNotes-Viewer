# Changelog

## [Unreleased]

### To Do

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
- why is app stripping out YYYY-mm-dd from filename when opening / sync?

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

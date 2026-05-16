# Changelog

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

# Apple Notes Viewer — CLAUDE.md

Local single-page web app for browsing and searching Apple Notes exports
produced by [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter).
**v3.0.0** — Python 3 stdlib only, no framework, no build step.

| File | Role |
|:-----|:-----|
| `server.py` | `ThreadingHTTPServer` — indexes notes, serves API + static files |
| `app.html` | Single-file SPA — all CSS and JS inline |
| `sync.sh` | Shell wrapper: `notes-export export --incremental` (macOS only) |
| `Launch Notes.command` / `.bat` | Double-click launchers (macOS / Windows) |
| `config.json` | Gitignored — `{"notes_root": "/abs/path"}` |
| `docs/ARCHITECTURE.md` | Deep architectural notes — read when changing internals |
| `docs/API.md` | HTTP endpoint reference |
| `docs/TEST_PLAN.md` | Pre-release manual test checklist |

---

## Gotchas — read before making changes

These are the "easy to get wrong, hard to debug" facts. Anything deeper is in
`docs/ARCHITECTURE.md`.

**Async startup race.** POST `/settings` and `/api/sync` must set
`_state["index_progress"]["active"] = True` *inside the handler*, before
spawning the rebuild thread, or the client's first poll sees stale state and
redirects with wrong data.

**Atomic sync claim.** POST `/api/sync` reads `active` and sets it under one
`with _lock` block. Splitting the read and write reintroduces a race.

**Per-segment URL encoding.** Folder names can contain `#`. Path segments are
encoded individually with `encodeURIComponent` so `#` → `%23`, not a URL
fragment. The static handler `unquote()`s on the way in.

**Live DOM for URL rewrites.** Step 2 of `renderNote()` rewrites `src`/`href`
on the **live** DOM (not the DOMParser doc). Chrome's `innerHTML` serialiser
decodes `%23` → `#`, which breaks PDF links in notes whose attachment folder
contains a `#tag`. Don't move this work back into the detached doc.

**`<embed>` is blank in Safari.** Always replace `<embed>`/`<object>` PDFs with
`<iframe>`. Also: only the **outermost** `[data-pdf-href]` card is replaced
(inner ones are skipped via `closest()`).

**Empty `<h1>` with image content.** Step 4's hashtag-h1 suppression must
check for visual children (`img, video, svg, canvas, object, embed`) before
hiding an empty-text `<h1>`. Notes saved from the iPhone share sheet are
`<h1><img …></h1>` — visible image, empty `textContent`.

**Filename scheme parity.** `_detect_export_prefix_args()` matches the export
folder's existing scheme (date-prefix vs none). A forced mismatch makes the
incremental manifest treat every note as new and silently duplicates the
library. Never weaken the detection or hardcode the scheme. `sync.sh` does
NOT auto-detect — only the in-app Sync.

**Cloud-sync folders are dangerous.** A `notes_root` inside Syncthing/Dropbox/
iCloud Drive propagates cross-machine deletes in, which looks like data loss.
`_prune_orphan_attachments` aborts if fewer than `_GATE_THRESHOLD` (75%) of
`pre_sync_count` notes are still on disk. Denominator must be
`pre_sync_count` (captured before the export) — `len(watermark_entries)` is
cumulative and grows over time, causing false gate fires.

**Three orphan-cleanup guards.** `_IMAGE_EXTS` skip (images are dual-written
by the exporter, never path-referenced); `if not referenced: continue` (HTML
has no path-refs into the folder); mtime guard (file is newer than the HTML).
Removing any one re-enables a real false-deletion class. The watermark is
used **only** for the consistency gate, not for per-file detection.

**Delete = unlink + watermark prune.** `POST /api/note/delete` removes the
HTML, the `(Attachments)/` folder, AND the watermark entry keyed by
`exportedPath`. If the watermark entry survives, the incremental exporter
sees the note as already-exported and never restores it after a sync.

**Recently Deleted is indexed.** `_SKIP_FOLDERS` is empty;
`_RECENTLY_DELETED_FOLDERS` marks notes with `recently_deleted: True`. The
client renders a red badge + warning banner. Don't add them back to
`_SKIP_FOLDERS` — the badge IS the user signal.

**Force Full Re-export is the only signal for in-Apple-Notes folder moves.**
The incremental exporter cannot detect a note moving between Apple Notes
folders (most importantly into Recently Deleted) — its `modificationDate`
doesn't change. `--reset-sync` wipes the watermark first; after the export
`_detect_stale_html_files()` finds HTML at old paths. Never call
`_detect_stale_html_files()` after a non-reset sync (the cumulative
watermark would falsely flag long-deleted notes' files).

**Benign no-op is success.** `notes-export` exits non-zero when there's
nothing to do ("All notes are up to date…"). The export phase scans stderr
for benign phrases and normalises `exit_code` to 0. Never revert to a bare
`returncode != 0` failure check.

**Stderr `done` ≠ note count.** `sync_progress["done"]` counts non-empty
stderr lines, NOT notes — the exporter emits >1 line/note in an unverified
format. The client clamps `done` to `total` (only set for full exports) for
a % bar; incremental shows an honest indeterminate sweep. Never parse the
stderr stream into a note name (that produced garbage like `1683]`).

**Index version bumps on `_rebuild()`.** `_state["index_version"]` is the
client cache key returned by `/api/index-status`. The browser short-circuits
`/api/notes` fetches when version + folder are unchanged. Don't forget to
bump it if you ever change `_rebuild()` to skip the swap.

---

## Persistence

`config.json` (gitignored) — notes folder path only.
`localStorage` — theme (`notes-theme`), panel widths (`notes-sidebar-w`,
`notes-list-w`), sort mode (`notes-sort`), attachment filter
(`notes-attach-filter`). Nothing else is written to disk.

## Tunable thresholds (named constants in `server.py`)

`_GATE_THRESHOLD` (0.75), `_PREFIX_DETECT_THRESHOLD` (0.80),
`_DRIFT_THRESHOLD_ABS` (10), `_DRIFT_THRESHOLD_PCT` (0.02),
`_MAX_REFERENCED_HTML_SIZE` (10 MB), `_INDEX_READ_MAX` (64 KB),
`_SEARCH_BODY_MAX` (8 KB), `_EXPORT_TIMEOUT_SEC` (300),
`_REINDEX_WAIT_TIMEOUT_SEC` (600), `_LIVE_LINES_MAX/_KEEP/_TAIL`
(1000/800/200).

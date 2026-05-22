# Apple Notes Viewer — Architecture Notes

Deeper rationale than the gotcha-list in the top-level `CLAUDE.md`. Read this
when changing internals.

## Thread-safe state

A single `_state` dict guarded by `_lock`. `_rebuild()` builds new note/index/
folders/tags collections in local variables, then swaps them atomically under
the lock. Each request handler calls `_snap()` → shallow dict copy.

Because list-and-dict values inside `_state` are *replaced by reference* on
rebuild (never mutated in place after initial construction), iteration over a
snapshot is safe even if `_rebuild()` runs mid-request — the handler holds the
old list, the new one is built independently. Python's GIL guarantees the
reference swap itself is atomic.

## Index versioning

`_state["index_version"]` bumps on every `_rebuild()`. Returned by GET
`/api/index-status`. The client caches `allNotes` keyed by
`(currentFolder, indexVersion)` and short-circuits the next `/api/notes`
fetch when both match. Eliminates 600 KB–1.5 MB JSON round-trips per folder
click on large libraries. Search results always refetch (the query string is
the cache-buster).

## `notes_root` vs `configured_root`

`_state["notes_root"]` is only set when the folder exists on disk.
`_state["configured_root"]` always holds the raw config string. The Settings
page falls back to `configured_root` so a stale path from another Mac shows
in the field — letting the user correct it rather than seeing an empty
input.

## Export depth filter

The exporter produces `{Account}/{Folder}/{Title}.html` (depth 3, optionally
with a `YYYY-MM-DD ` prefix). Indexing keeps only depth-3 HTML files;
attachment subdirs at depth 4 are skipped. `_SKIP_FOLDERS` is empty;
`_RECENTLY_DELETED_FOLDERS` (`"recently deleted"`, `"trash"`, `"deleted items"`,
lowercase) marks notes with `recently_deleted: True` — they're indexed
normally but flagged for the UI.

## Capped reads during indexing

`build_index()` reads at most `_INDEX_READ_MAX` (64 KB) bytes per note. The
`<title>` and `<meta name="modified">` tags are always within the first ~1 KB.
The snippet caps at 280 chars; the search corpus caps at `_SEARCH_BODY_MAX`
(8 KB) of body text. For an export with multi-MB base64 image notes this
drops peak indexing memory by ~6× without measurable search-quality loss.

## Date source

`<meta name="modified" content="D Mon YYYY at H:MM am/pm">` parsed first
(format `"%d %b %Y at %I:%M %p"` e.g. `"5 Dec 2019 at 6:28 am"`). Falls back
to file mtime if absent/unparseable — survives rsync/OS migration that
corrupts mtime. The `YYYY-MM-DD ` filename prefix is **never** a date source
— purely cosmetic.

## Tag extraction

Dual-source, two thresholds:
- `_stem_tags` from filename (authoritative; shown if count ≥ 1)
- `body_tags` from text (noise filter; shown only if count ≥ 2)

`_TAG_RE` matches letter-start tags ≥ 2 chars (`#AI`) and digit-start tags
with ≥ 1 letter (`#10SmallSt`, `#60thBigBash`). `_TAG_BLOCKLIST` filters
common false positives from URL fragments. 6–8 char pure-hex tags are
filtered as likely commit/colour hashes.

## PDF rendering pipeline

1. `<embed>`/`<object>` pointing at PDFs are replaced with `<iframe>` (Safari
   renders `<embed type="application/pdf">` blank).
2. Apple-notes-exporter card structure (`<a>` inside a styled flex `<div>`)
   is replaced with an inline `<iframe>`.
3. URL rewriting and `data-pdf-href` marking happen on the **live** DOM —
   never the detached DOMParser doc — because Chrome's `innerHTML`
   serialiser decodes `%23` → `#`.
4. Only the outermost `[data-pdf-href]` element is replaced; inner ones are
   guarded via `closest()`.
5. A delegated click listener on `#contentPanel` catches `.pdf` links the
   marking pass missed.

## Exporter `<pre>` fragmentation

`apple-notes-exporter` wraps every text run between bold markers in its own
`<pre style='background:#f5f5f5'>`. `renderNote()` Step 5 collapses
consecutive runs (fingerprint: `background:\s*#f5f5f5`), strips `**` bold
delimiters, converts markdown headings/bullets, collects pipe-table rows
into a single monospace block, and outputs one `.exporter-prose` div. All
processing is on live DOM nodes.

## Sync progress state

`_state["sync_progress"]` = `{active, done, total, current, error, lines}`.

- `done`: count of non-empty stderr lines from `--verbose` — NOT a note
  count (freeform stream, >1 line/note). Climbs past the real note count.
- `total`: set only for *full* exports (no watermark) via `list-notes
  --format json`. Client clamps `done` to it for a real % bar. Incremental
  syncs leave it 0 and the client shows an indeterminate sweep.
- `lines`: in-memory accumulator capped at `_LIVE_LINES_MAX` (1000); last
  `_LIVE_LINES_KEEP` (800) kept when trimmed. GET `/api/sync` returns the
  last `_LIVE_LINES_TAIL` (200) for the live pane.

## Benign no-op exit

`notes-export` exits non-zero when there's nothing to export ("All notes
are up to date, nothing to export."). The export phase scans stderr for
benign phrases (`nothing to export`, `all notes are up to date`, `no notes
to export`, `no changes`) and normalises `exit_code` to 0 when matched.

## Sync log schema

`_state["sync_log"]` is a structured dict assembled across all phases:

```
{
  timestamp, type, reset_sync, scheme,
  export:    {duration_s, stderr_lines[≤500], stderr_total, exit_code,
              error, exporter_total, deleted_notes[]},
  cleanup:   {files_removed, bytes_freed, dirs_removed, items[], skipped,
              skip_reason},
  reindex:   {notes_indexed, duration_s, error?},
  drift:     {detected, stale_count, indexed, exporter_total},
  stale_files: [{path, title, size}, …],   // reset_sync only
  full_log:  [str, …],                       // exporter stderr + cleanup actions
  total_duration_s,
  log_complete: bool
}
```

Served by `GET /api/sync-log`. The Sync Report modal renders one card per
phase. `full_log` is captured from `sync_progress["lines"]` after the
cleanup phase emits its final action lines (`_emit_sync_line()` is the
thread-safe appender). `_wait_for_reindex` writes `log_complete: True`
once `index_progress.active` goes False — or after
`_REINDEX_WAIT_TIMEOUT_SEC` (10 min) as a safety cap so the wait thread
never leaks if `_rebuild()` crashes silently.

## Orphan attachment cleanup

`notes-export` is additive. `_prune_orphan_attachments()` scans every
`(Attachments)/` folder on disk, parses `href`/`src` in the corresponding
note HTML, and deletes unreferenced **non-image** files. Three guards
prevent false deletions:

1. `_IMAGE_EXTS` — images are dual-written by the exporter (base64 inline
   AND a raw copy in `(Attachments)/`). The raw copy is never referenced
   by path; without this guard it would always appear orphaned.
2. `if not referenced: continue` — if the HTML has zero path-refs into the
   folder, skip entirely. All-base64 (nothing to clean) or stale-HTML
   match (wrong source of truth).
3. mtime guard — files newer than the HTML are skipped (HTML predates
   them, can't reference them).

The watermark is used **only** for the consistency gate. Gate denominator
is `pre_sync_count` (notes indexed before this export), NOT
`len(watermark_entries)` — the watermark is cumulative and grows over time.

## Force Full Re-export (`reset_sync`)

POST `/api/sync` accepts `{"reset_sync": true}`. The flag flows through
`_run_export_async(reset_sync=True)`, which appends `--reset-sync` to the
exporter command. The watermark is wiped first, so every note is re-
exported to its current Apple Notes location.

**This is the only signal for Apple-Notes-internal folder moves** —
critically including notes moved to Recently Deleted. The incremental
exporter cannot detect those because `modificationDate` does not change
on a folder move.

After a reset run, `_detect_stale_html_files()` scans the fresh
watermark's `exportedPath` set against on-disk depth-3 HTML files. Files
not in the set are stale (permanently-deleted notes' surviving HTML, or
old copies left at the previous folder). Surfaced as the "Stale HTML
files on disk" card in the Sync Report. Never call this function after a
non-reset sync — the cumulative watermark contains entries for long-
deleted notes whose files do still exist.

## Note deletion handling

`POST /api/note/delete` has six guards:
1. `notes_root` must be set
2. Path must resolve cleanly
3. Resolved path must be inside `notes_root`
4. Depth must be exactly 3 (`Account/Folder/Note.html`)
5. Suffix must be `.html`
6. File must exist

On success: unlink the HTML, recursively remove the `(Attachments)/`
folder, **and** remove the matching watermark entry. The watermark step
is critical — without it, the incremental exporter sees the note as
already-exported and never restores it after a sync.

## Sync Report modal flow

Opens at sync start in **live mode** (× disabled, inactivity-based force-
close at 60s without new output as the escape hatch). Transitions to
**re-index mode** when export completes. Transitions to **report mode**
(full phase cards) when re-index completes. Blocks on the "Done — return
to notes" button before calling `loadFolders → loadTags → loadNoteList` —
ensures the user sees what changed before the list refreshes. The Log
button in the sidebar footer re-opens the latest report at any time.

`window._syncLog = {openLive, updateLive, updateReindex, showReport, showError}`.

## CSS / DOM notes

- All styles inline in `app.html`. No build step.
- Theme is `data-theme="dark|light"` on `<html>`. Selectors use the
  attribute to override CSS variables in the dark block.
- Toggle controls use `aria-pressed` and `:focus-visible` outlines.
- Modals trap focus on open via `setTimeout(() => element.focus(), 0)`
  with `tabindex="-1"` on the focus target.

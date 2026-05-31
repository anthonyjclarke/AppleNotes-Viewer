# Apple Notes Viewer — HTTP API Reference

The server binds to `127.0.0.1:8765` (loopback only — never exposed to the
network). All responses are JSON unless noted. Status codes are 200 except
where stated.

Used by `app.html` (single-file SPA). Stable for in-app use; consider
unstable for external integrations until 3.x settles.

---

## GET endpoints

### `/` / `/index.html`
Serves the SPA (`app.html`).

### `/settings`
Serves the Settings page (server-rendered HTML). Available even when
`notes_root` is unset (first-run guard exempt). Shows a **← Back** button
when a path is already configured.

### `/api/notes?folder=<folder>`
List of notes (sorted newest-first by date). `folder` is `__all__` to get
every note, or e.g. `iCloud/Notes` to scope.

```json
[
  {
    "file": "iCloud/Notes/2024-06-15 Holiday plans.html",
    "folder": "iCloud/Notes",
    "title": "Holiday plans",
    "date": "2024-06-15",
    "snippet": "Lorem ipsum…",
    "size": 8472,
    "has_attachments": false,
    "recently_deleted": false
  }
]
```

The client caches this response by `(folder, index_version)` to skip
redundant fetches across folder switches.

### `/api/search?q=<query>&folder=<folder>`
Substring search over title + indexed body text for every note in `folder`
(or all notes when `folder=__all__`). Case-insensitive. The indexed body
text is capped at the first 8 KB extracted from each note during indexing.
`q` must be ≥ 2 chars or all notes in the pool are returned.

Response shape identical to `/api/notes`.

### `/api/note?file=<relpath>`
Returns the raw exported HTML document for one note. `relpath` is the full
`Account/Folder/Title.html` path (URL-encoded). Returns 404 if the path is
unknown, contains `..`, or doesn't match a note in the live index.

### `/api/folders`
Folder list for the sidebar, grouped by account.

```json
{
  "total": 1758,
  "groups": [
    {
      "label": "iCloud",
      "folders": [
        {"name": "Notes",            "path": "iCloud/Notes", "count": 1700, "deleted": false},
        {"name": "Recently Deleted", "path": "iCloud/Recently Deleted", "count": 12, "deleted": true}
      ]
    }
  ]
}
```

### `/api/tags`
All tags above the visibility threshold.

```json
[
  {"tag": "#health", "count": 23},
  {"tag": "#travel", "count": 14}
]
```

A tag appears if it's in ≥ 1 filename (`_stem_tags`, authoritative) or in
≥ 2 body texts (noise filter for body-only tags).

### `/api/sync`
Current sync status + last ~200 stderr lines for the live output pane.

```json
{
  "last_synced": "2026-05-22T16:30:00",
  "count": 1758,
  "sync_progress": {
    "active": true,
    "done": 142,           // non-empty stderr lines — NOT a note count
    "total": 1758,         // 0 for incremental syncs (indeterminate)
    "current": "Exporting notes…",
    "error": null,
    "lines": [/* ringbuffer of stderr */]
  },
  "live_lines": ["…"]      // last 200 — for the live modal pane
}
```

### `/api/sync-log`
The structured report from the last completed sync. See the schema in
`docs/ARCHITECTURE.md`. Returns `{"available": false}` when no sync has
been run yet.

Use `log_complete: true` as the readiness signal — partial logs are
written immediately after the export phase so the client always has
export+cleanup data, but `reindex` stats are filled in by a follow-up
thread.

### `/api/index-status`
Server version + index state.

```json
{
  "active": false,           // true while a re-index is running
  "done": 1758,
  "total": 1758,
  "count": 1758,             // total notes currently indexed
  "version": "3.0.0",        // APP_VERSION
  "index_version": 4         // bumps on every _rebuild() — client cache key
}
```

### `/api/browse?path=<dir>`
Directory listing for the Settings folder picker. Returns the path's
subdirectories (dotfiles filtered out) and the parent path for the "↑ Go
up" affordance. Falls back to the user's home directory if the requested
path doesn't exist.

```json
{
  "path": "/Users/you/Documents/AppleNotes",
  "parent": "/Users/you/Documents",
  "entries": [
    {"name": "iCloud", "path": "/Users/you/Documents/AppleNotes/iCloud"}
  ]
}
```

This endpoint is exempt from the first-run redirect guard so the picker
works on first launch.

### `/static/<relpath>`
Serves an attachment file (PDF, image) from inside `notes_root`. The path
is validated to stay inside `notes_root` (no `..`) and 503s if no folder
is configured.

---

## POST endpoints

### `POST /settings`
Body: `{"notes_root": "/abs/path"}`. Validates the path exists and is a
directory, writes `config.json`, kicks off re-index in a background
thread. Returns `{"status": "indexing"}` immediately.

### `POST /api/sync`
Body (optional): `{"reset_sync": false}`. Setting `true` passes
`--reset-sync` to the exporter, wiping the watermark first and forcing
every note to be re-exported. Use for cleaning up Apple-Notes-internal
moves (especially into Recently Deleted).

Returns `{"status": "syncing", "reset_sync": false}` immediately if the
export started, or `{"status": "syncing"}` if a sync is already running.
Errors return `{"status": "error", "message": "..."}`.

Windows returns 200 with an error message — sync requires macOS.

### `POST /api/note/delete`
Body: `{"file": "iCloud/Notes/Foo.html"}`. Six safety guards (see
ARCHITECTURE). Returns:

```json
{
  "ok": true,
  "attachments_count": 3,
  "bytes_freed": 1048576
}
```

Or on failure: `{"ok": false, "error": "…"}`. Removes the HTML file, the
matching `(Attachments)/` folder, and the watermark entry keyed by
`exportedPath` (the watermark step makes the next sync re-export the note
if it still exists in Apple Notes).

---

## Conventions

- All paths are POSIX-style (forward slashes) regardless of host OS.
- Errors use HTTP 200 with `{"ok": false}` / `{"status": "error"}` for
  application-level failures so the client can render the message; only
  truly malformed requests get a 4xx.
- All `_`-prefixed keys in the internal note dict are stripped before
  sending to the client (`_search`, `_path`, `_tags`, `_stem_tags`).
- All endpoints set `Cache-Control: no-cache`. The static file handler
  does not — the browser caches attachments by URL.

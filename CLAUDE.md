# Apple Notes Viewer — CLAUDE.md

## What this project is

Local single-page web app for browsing and searching Apple Notes exports produced by
[`apple-notes-exporter`](https://github.com/nicholasstephan/apple-notes-exporter) CLI.
v2.0 — complete rewrite from the Falcon Notes Exporter-based v1. Python 3 stdlib only,
no framework, no build step.

---

## Architecture

| File | Role |
|:-----|:-----|
| `server.py` | Python 3 `ThreadingHTTPServer` — indexes notes, serves API + static files |
| `app.html` | Single-file SPA — all CSS and JS inline |
| `sync.sh` | Shell wrapper: calls `apple-notes-exporter --incremental`, reads path from `config.json` |
| `Launch Notes.command` | Double-click Finder launcher — kills old instance, opens browser |
| `config.json` | Gitignored — `{"notes_root": "/abs/path/to/export"}` |

---

## Key architectural decisions and WHY

**Async startup** — server binds immediately; indexing runs in a daemon thread.
`_state["notes_root"]` and `_state["index_progress"]["active"] = True` are set from
config *before* the HTTP server starts, so the first-run redirect guard works instantly
and the browser opens right away to a loading screen.

**Race condition guard** — POST `/settings` and POST `/api/sync` both set
`_state["index_progress"]["active"] = True` atomically *before* calling
`_start_rebuild_async()`. Without this, the client's first poll sees the previous
run's stale `active: False` and redirects to `/` with old data.

**Thread-safe state** — single `_state` dict + `_lock` (threading.Lock). `_rebuild()`
builds a complete replacement state then swaps it in one `with _lock:` block.
Each request calls `_snap()` → shallow copy, reads that snapshot only.

**Export depth filter** — apple-notes-exporter produces
`{Account}/{Folder}/{yyyy-MM-dd} {Title}.html`. Attachment subdirs are at depth 4.
`len(f.relative_to(notes_root).parts) == 3` is the only filter needed.
`_SKIP_FOLDERS = {"Recently Deleted"}` excludes that Apple Notes system folder.

**Per-segment URL encoding** — folder names can contain `#` (Apple Notes hashtag
folders). Path segments are encoded individually with `encodeURIComponent` so `#`
becomes `%23`, not a URL fragment. The static handler uses `unquote()` to decode.

**Date source** — every exported HTML has `<meta name="modified" content="D Mon YYYY
at H:MM am/pm">`. This is parsed first; mtime is the fallback. Meta tag survives
rsync or OS migration that would corrupt mtime.

**PDF modal — card marking** — apple-notes-exporter attachment cards are structured
`flex-card > flex-1-div > <a href="…pdf">`. During rewriting, BOTH the `<a>` AND its
grandparent flex-card get `data-pdf-href` so clicks on the emoji icon or "Scan File"
text (siblings of `<a>`, not descendants) still open the modal. One delegated listener
on `#contentPanel` handles all PDF clicks via `e.target.closest("[data-pdf-href]")`.

---

## Persistence

`config.json` (gitignored) — Notes folder path only. `localStorage` — panel widths
(`notes-sidebar-w`, `notes-list-w`) and theme. Nothing else is written to disk.

---

## Never do

- Never call `_rebuild()` synchronously from a request handler — it holds `_lock`
  for the full index duration and starves other threads.
- Never set `active: True` only inside `build_index()` — the POST handler must set it
  first or the race condition returns.
- Never use `a.href` (resolved property) to check rewritten paths — always
  `a.getAttribute("href")` which returns the literal attribute value.
- Never commit `config.json` — it contains absolute local paths.
- Never increase the `sleep` in `Launch Notes.command` as a fix for slow startup —
  the server now starts async and the app shows a loading screen.

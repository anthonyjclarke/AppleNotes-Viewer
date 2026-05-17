# Apple Notes Viewer — CLAUDE.md

## What this project is

Local single-page web app for browsing and searching Apple Notes exports produced by
[`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter) CLI.
v2.4 — Python 3 stdlib only, no framework, no build step.

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

**Export depth filter** — exporter produces `{Account}/{Folder}/{date} {Title}.html` (depth 3).
`len(f.relative_to(notes_root).parts) == 3` is the only filter; attachment subdirs (depth 4)
are skipped. `_SKIP_FOLDERS = {"Recently Deleted"}` excludes that system folder.

**Per-segment URL encoding** — folder names can contain `#` (Apple Notes hashtag
folders). Path segments are encoded individually with `encodeURIComponent` so `#`
becomes `%23`, not a URL fragment. The static handler uses `unquote()` to decode.

**Date source** — `<meta name="modified" content="D Mon YYYY at H:MM am/pm">` parsed
first; mtime is the fallback (survives rsync/OS migration that corrupts mtime).

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
- Never commit `config.json` — it contains absolute local paths.
- Never increase the `sleep` in `Launch Notes.command` — the server starts async and
  shows a loading screen; sleeping longer does not fix slow startup.

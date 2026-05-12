# Apple Notes Viewer — CLAUDE.md

## What this project is

Local single-page web app for browsing and searching Apple Notes exports produced by
[`apple-notes-exporter`](https://github.com/nicholasstephan/apple-notes-exporter) CLI.
v2.1 — Python 3 stdlib only, no framework, no build step.

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

**Race condition guard** — POST `/settings` and POST `/api/sync` set
`_state["index_progress"]["active"] = True` *before* calling `_start_rebuild_async()`.
Without this, the client's first poll sees stale `active: False` and redirects with old data.

**Thread-safe state** — single `_state` dict + `_lock`. `_rebuild()` builds a complete
replacement then swaps it atomically. Each request calls `_snap()` → shallow copy only.

**`notes_root` vs `configured_root`** — `_state["notes_root"]` is only set when the
folder exists on this machine; `_state["configured_root"]` always holds the raw config
string. Settings falls back to `configured_root` so a stale path from a different Mac
is shown in the field rather than blank.

**First-run guard exceptions** — `_SETTINGS_PATHS = {"/settings", "/favicon.ico",
"/api/browse"}`. The browse API must be in this set; if excluded, the Settings page
folder picker silently fails whenever `notes_root` is `None`.

**Export depth filter** — apple-notes-exporter produces `{Account}/{Folder}/{yyyy-MM-dd} {Title}.html`.
Attachment subdirs are depth 4. `len(f.relative_to(notes_root).parts) == 3` is the only
filter needed. `_SKIP_FOLDERS = {"Recently Deleted"}` excludes that system folder.

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

**PDF modal — `<iframe>` not `<embed>`** — `<embed>` renders blank in Safari. All URL
rewriting and `data-pdf-href` marking runs on live DOM elements after `noteBody.innerHTML`
is set — not in the detached DOMParser doc, where Chrome's `innerHTML` serialiser decodes
`%23` back to `#`, breaking PDF links in notes with `#` in their attachment folder name.
Delegated listener on `#contentPanel` uses `closest("[data-pdf-href]")` with a `.pdf`
href fallback to catch any link the marking pass missed.

**Indeterminate scan phase** — `build_index()` calls `rglob("*.html")` before the
total count is known. During this phase (`index_progress.total == 0`), both the startup
overlay and the Settings progress bar show an animated sweep bar + "Scanning notes
folder…" rather than a useless "0 / 0" label.

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
- Never use `<embed type="application/pdf">` for the PDF modal — only `<iframe>` renders
  reliably across Safari and Chrome on macOS.
- Never remove `/api/browse` from `_SETTINGS_PATHS` — the Settings folder picker
  silently breaks when `notes_root` is `None`.
- Never rewrite URLs or set `data-pdf-href` in a detached DOMParser document —
  Chrome's `innerHTML` serialiser decodes `%23` back to `#` in URL attributes, breaking
  PDF links in notes whose attachment folder contains a `#tag`.
- Never commit `config.json` — it contains absolute local paths.
- Never increase the `sleep` in `Launch Notes.command` as a fix for slow startup —
  the server starts async and the app shows a loading screen.

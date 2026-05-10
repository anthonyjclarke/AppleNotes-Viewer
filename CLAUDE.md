# AppleNotes-Viewer — Claude Code Context

## What this project is

A zero-dependency local web viewer for Apple Notes exported as HTML. A Python stdlib server (`server.py`) indexes `Notes/` at startup and exposes a JSON API; `app.html` is a single-file vanilla JS SPA (no build step). Runs at `http://127.0.0.1:8765`. Double-click `Launch Notes.command` to start.

Current version targets Falcon-exported HTML. Active dev branch is integrating `apple-notes-exporter` CLI — see `docs/apple-notes-exporter-integration.md`.

---

## Architecture decisions

- **Single-file frontend** — `app.html` is intentionally one file with embedded CSS and JS. No bundler, no framework. Don't introduce build tooling or external frontend dependencies.
- **Python stdlib only** — `server.py` uses no third-party packages. Keep it that way.
- **In-memory index** — built at server startup from `Notes/*.html` files. No database, no cache file written to disk.
- **Depth-3 rule** — only `{Account}/{Folder}/{Note}.html` files are indexed. Files at other depths (images, attachments) are skipped.
- **Port 8765** — hardcoded, localhost only. Not configurable; not exposed to the network.

---

## Notes/ directory

- Gitignored contents (`Notes/*`) — real notes never committed.
- `Notes/.gitkeep` tracks the empty directory.
- Expected structure: `Notes/{Account}/{Folder}/{Note}.html`
- Falcon exporter puts images in `{Folder}/images/` and attachments in `{Folder}/attachments/`.
- apple-notes-exporter (integration in progress) embeds images as base64 and puts attachments in `{Folder}/{NoteTitle}/`.

---

## make_demo.py

**Test data generator — not part of the app.** Gitignored from the repo itself (it's a dev tool) but the data it produces (`Notes/Demo/`) is committed for use in the GitHub repo so visitors can clone and immediately try the app without needing their own Apple Notes export.

- Creates `Notes/Demo/` with Personal, Work, Recipes, Travel subfolders (34 notes)
- Downloads 5 real images from Picsum Photos and generates 2 valid PDFs
- Sets file `mtime` to realistic timestamps so date grouping works correctly
- Safe to re-run — overwrites existing demo data
- Run it when demo content needs refreshing for screenshots or repo updates

Do not run `make_demo.py` as part of any server startup or sync flow. It is a one-shot tool for maintainers only.

---

## Key files

| File | Purpose |
|:-----|:--------|
| `server.py` | HTTP server + note indexer |
| `app.html` | Single-file SPA frontend |
| `Launch Notes.command` | macOS double-click launcher |
| `sync.sh` | (planned) apple-notes-exporter CLI wrapper |
| `docs/apple-notes-exporter-integration.md` | Integration plan for new sync workflow |
| `Notes/` | Note data — gitignored contents |

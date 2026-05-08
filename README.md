# Apple Notes Viewer

A local web app for browsing and searching your Apple Notes exports. Runs entirely on your Mac — no cloud, no accounts, no external dependencies beyond Python 3.

> Built to work with exports from [Falcon Notes Exporter](https://falcon.star-lord.me/exporter).

---

<!-- SCREENSHOT: Full three-column UI in light mode — sidebar with folders and tags, note list, note content open -->

---

## Features

- **Three-column layout** — sidebar, note list, and content pane; mirrors the Apple Notes desktop experience
- **Full-text search** — searches complete note body text, not just visible snippets; results as you type
- **Folder scoping** — browse a single folder or search across all notes with one click
- **`#tag` sidebar** — automatically detects hashtags in note bodies and lists them for one-click filtering
- **Last-edited sort order** — notes sorted by last-edited date (matching iPhone), not creation date
- **Resizable columns** — drag the divider between the note list and content pane; preference is saved
- **Image lightbox** — click any embedded image to open it full-screen
- **Light and dark mode** — toggle in the sidebar; preference persists across sessions
- **No dependencies** — Python 3 stdlib only; one command to run

---

## Screenshots

### Light mode

<!-- SCREENSHOT: Light mode — full UI showing sidebar with tag list, note list with date groups, and a note with inline images open -->

### Dark mode

<!-- SCREENSHOT: Dark mode — same layout, warm dark palette -->

### Search

<!-- SCREENSHOT: Search active — query typed, results highlighted in yellow in both title and snippet, "Search all notes" pill visible -->

### Tag filtering

<!-- SCREENSHOT: Tag clicked in sidebar — search box auto-populated with #tag, filtered results shown -->

---

## Requirements

- macOS (tested on Sonoma)
- Python 3.9 or later (pre-installed on macOS)
- [Falcon Notes Exporter](https://falcon.star-lord.me/exporter) to produce the HTML export

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/anthonyjclarke/apple-notes-viewer.git
cd apple-notes-viewer
```

### 2. Export your notes with Falcon

1. Download and install [Falcon Notes Exporter](https://falcon.star-lord.me/exporter)
2. Open Falcon, select your Notes account and folders, and export as **HTML**
3. Falcon produces a folder named after your account — typically `On My Mac` or your iCloud account name

### 3. Place the export folder

Move the exported folder into the `Notes/` directory inside the project:

```
apple-notes-viewer/
└── Notes/
    └── On My Mac/       ← your exported folder goes here
        ├── Note Title-DD-MM-YYYY.html
        ├── images/
        └── attachments/
```

For multiple accounts, place each alongside the others:

```
Notes/
├── On My Mac/
└── iCloud/
```

### 4. Launch

Double-click **`Launch Notes.command`** in Finder. macOS will open Terminal, start the server, and open the app in your browser at `http://127.0.0.1:8765`.

To stop the server, close the Terminal window.

---

## Updating your notes

When you run a fresh export from Falcon:

1. Stop the server (close the Terminal window)
2. Delete the old account folder inside `Notes/`
3. Move the new export folder into `Notes/`
4. Double-click `Launch Notes.command` to relaunch

The server re-indexes everything on startup. Full instructions are in [`NOTES_VIEWER.md`](NOTES_VIEWER.md).

---

## How it works

`server.py` is a zero-dependency Python HTTP server. On startup it walks the `Notes/` directory, parses every HTML file, and builds an in-memory index of titles, body text, hashtags, and last-edited dates. The index is held in memory for the session — nothing is written to disk.

`app.html` is a single-file SPA that fetches from the server's JSON API and renders the UI. No build step, no framework.

| File                   | Purpose                                                              |
|:-----------------------|:---------------------------------------------------------------------|
| `server.py`            | HTTP server — indexes notes at startup, serves API and static files  |
| `app.html`             | Single-page UI — layout, search, tag sidebar, lightbox               |
| `Launch Notes.command` | Double-click launcher — kills old instance, starts server, opens browser |
| `Notes/`               | Export container — place Falcon export folders here                  |

Notes are sorted by **last-edited date**. Falcon sets each exported file's modification time to the note's last-edit timestamp from Apple Notes, so the sort order matches iPhone exactly.

---

## Keyboard shortcuts

| Key         | Action                                       |
|:------------|:---------------------------------------------|
| `/` or `⌘F` | Focus search                                 |
| `↑` / `↓`  | Move between notes                           |
| `Escape`    | Clear search / deselect tag / close lightbox |

---

## Operational guide

[`NOTES_VIEWER.md`](NOTES_VIEWER.md) covers the full operational detail: folder layout, UI reference, update workflow, tag detection rules, troubleshooting, and technical reference.

---

## License

MIT

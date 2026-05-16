# Apple Notes Viewer

A local web app for browsing and searching your Apple Notes exports. Runs entirely on your Mac — no cloud, no accounts, no external dependencies beyond Python 3.

> **v2.2** — Built around [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter). See [CHANGELOG.md](CHANGELOG.md) for what changed.

---

<!-- SCREENSHOT: Full three-column UI in light mode — sidebar with folders and tag pills, note list, note content open -->

---

## Features

- **Three-column layout** — sidebar, note list, and content pane; mirrors the Apple Notes desktop experience
- **Full-text search** — searches complete note body text, not just visible snippets; results highlighted as you type
- **Folder navigation** — browse a single Apple Notes folder or search across all notes with one click
- **Tag pills** — detects `#hashtags` from note text and filenames, matching Apple Notes exactly (including digit-first tags like `#10SmallSt` and short tags like `#AI`); displayed as clickable pill chips
- **Last-edited sort order** — notes sorted by last-edited date, matching what you see on iPhone
- **Resizable columns** — drag either panel divider; preferences saved across sessions
- **PDF inline viewer** — PDF attachment cards are rendered directly in the note body as inline iframes; both Safari and Chrome display them natively without a separate viewer step
- **About panel** — "i" button in the sidebar opens version info, how-to-use guide, and attribution
- **Image lightbox** — click any embedded image to open it full-screen
- **Sync button** — re-runs the exporter incrementally and re-indexes, without restarting the server
- **Startup loading screen** — server is immediately available; a progress bar tracks the index while notes load
- **Light and dark mode** — toggle in the sidebar; preference persists
- **No runtime dependencies** — Python 3 stdlib only; one file to serve the whole app

---

## Screenshots

### Light mode

<!-- SCREENSHOT: Light mode — full UI showing sidebar with tag pills, note list with date groups, and a note open -->

### Dark mode

<!-- SCREENSHOT: Dark mode — same layout, warm dark palette -->

### Search

<!-- SCREENSHOT: Search active — query typed, results highlighted in yellow, "Search all notes" pill visible -->

### Tag filtering

<!-- SCREENSHOT: Tag pill selected in sidebar — filtered results shown -->

---

## Requirements

- macOS (tested on Sonoma / Sequoia)
- Python 3.9 or later (pre-installed on macOS)
- [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter) by Konstantin Zaremski — not available via Homebrew. Download the latest `.zip` from the [Releases page](https://github.com/kzaremski/apple-notes-exporter/releases), then:

```bash
# 1. Unzip and move the app to Applications (standard macOS install)
unzip AppleNotesExporter_v*.zip
mv "Apple Notes Exporter.app" /Applications/

# 2. Symlink the embedded CLI so it is available in Terminal
sudo ln -sf \
  "/Applications/Apple Notes Exporter.app/Contents/SharedSupport/notes-export" \
  /usr/local/bin/notes-export
```

> **Note:** Releases from v0.4 Build 5 onward are notarized. Older builds require a manual Gatekeeper exception in System Settings → Privacy & Security.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/anthonyjclarke/apple-notes-viewer.git
cd apple-notes-viewer
```

### 2. Export your notes

Run `apple-notes-exporter` and point it at a folder you own — a subdirectory of Documents works well:

```bash
notes-export export --format html --output ~/Documents/AppleNotes
```

This produces a folder structure like:

```
~/Documents/AppleNotes/
├── iCloud/
│   └── Notes/
│       ├── 2024-06-15 Holiday plans.html
│       └── 2024-06-15 Holiday plans (Attachments)/
└── On My Mac/
    └── Work/
        └── 2023-11-20 Meeting notes.html
```

The app needs the **parent** directory (e.g. `~/Documents/AppleNotes`) — the one that holds `iCloud/` and `On My Mac/` — not the folders inside.

### 3. Launch

Double-click **`Launch Notes.command`** in Finder. macOS opens Terminal, the server starts, and your browser opens at `http://127.0.0.1:8765`.

On **first launch** you will see the Settings page. Click **Browse…**, navigate to your export folder, click **Select This Folder**, then **Save & Index Notes**. A progress bar tracks the index; the app opens automatically when done.

To stop the server, close the Terminal window.

---

## Keeping notes up to date

### Initial export — capture everything

The setup step runs a **full export** with no `--incremental` flag:

```bash
notes-export export --format html --output ~/Documents/AppleNotes
```

This exports every note from every account and folder visible to Apple Notes on this Mac — including **On My Mac** folders (which are local to this machine and never sync via iCloud), as well as all iCloud accounts and any shared notebooks. Run this once when you first set up the app. It may take several minutes for large note collections.

> **On My Mac folders:** these notes live only on this Mac. They are captured in full on the initial export and picked up by subsequent syncs whenever a note in those folders is created or edited. They will not appear in exports run on a different machine.

### Ongoing sync — stay current

Click **↻ Sync** in the sidebar footer. This runs:

```bash
notes-export export --format html --incremental --output ~/Documents/AppleNotes
```

The `--incremental` flag reads a watermark file (`AppleNotesExportSyncWatermark.json`) that tracks the last-modified date of every exported note. Only notes newer than the watermark are re-exported, making repeated syncs fast even with thousands of notes. After the export completes, the app re-indexes and the note list refreshes automatically.

**For iCloud notes**, sync whenever you want to pull in notes created or edited on another device — iPhone, iPad, or another Mac. iCloud must have already synced those changes to this Mac before pressing ↻ Sync; the exporter reads directly from the local Apple Notes database, not from iCloud servers.

### Forcing a full re-export

If notes appear missing or out of date, you can reset the watermark and force a complete re-export:

```bash
notes-export export --format html --reset-sync --output ~/Documents/AppleNotes
```

This clears the watermark and re-exports every note, equivalent to a first-time export.

### Requirements for sync

`notes-export` must be on your `PATH` (placing it in `/usr/local/bin/` via the symlink described above is the simplest way). To use a binary at a custom path, set `NOTES_EXPORT_BIN` in your environment before launching the app.

---

## How it works

`server.py` is a zero-dependency Python HTTP server. On startup it binds immediately and kicks off indexing in a background thread — the browser opens right away and shows a loading screen until the index is ready. The index holds note titles, body text, hashtags, dates, and folder paths in memory for the session. Nothing is written to disk at runtime beyond `config.json`, which stores your chosen Notes folder path.

`app.html` is a single-file SPA that fetches from the server's JSON API and renders everything. No build step, no framework, no npm.

| File                   | Purpose                                                               |
|:-----------------------|:----------------------------------------------------------------------|
| `server.py`            | HTTP server — indexes notes, serves all API routes and static files   |
| `app.html`             | Single-page UI — layout, search, tag pills, PDF modal, lightbox       |
| `sync.sh`              | Sync script — wraps `notes-export export --incremental`               |
| `Launch Notes.command` | Double-click launcher — kills old instance, starts server, opens browser |
| `config.json`          | Local config — your Notes folder path (gitignored, never committed)   |

---

## Keyboard shortcuts

| Key         | Action                                            |
|:------------|:--------------------------------------------------|
| `/` or `⌘F` | Focus search                                      |
| `↑` / `↓`  | Navigate between notes in the list               |
| `Escape`    | Close PDF modal → close lightbox → clear search   |

---

## License

MIT

# Apple Notes Viewer

A local web app for browsing and searching your Apple Notes exports. Runs entirely on your machine — no cloud, no accounts, no runtime dependencies beyond Python 3.

> **v2.3** — Built around [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter). See [CHANGELOG.md](CHANGELOG.md) for what changed.

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
- **PDF inline viewer** — PDF attachment cards rendered directly in the note body as inline iframes; Safari and Chrome both display them natively
- **About panel** — "i" button in the sidebar opens version info, a how-to-use guide, and attribution
- **Image lightbox** — click any embedded image to open it full-screen
- **Sync button** — re-runs the exporter incrementally and re-indexes, without restarting the server (macOS only)
- **Startup loading screen** — server is immediately available; a progress bar tracks the index while notes load
- **Light and dark mode** — toggle in the sidebar; preference persists
- **No runtime dependencies** — Python 3 stdlib only; one file to serve the whole app

---

## Platform support

| | macOS | Windows |
|:--|:--|:--|
| View and search notes | Yes | Yes |
| Sync (re-export notes) | Yes — via `apple-notes-exporter` | Not available — export only runs on macOS |
| Launcher | `Launch Notes.command` | `Launch Notes.bat` |
| Python | Pre-installed | Must install manually |

**The exporter is macOS-only** — it reads directly from the Apple Notes database using macOS APIs. Windows is a read-only viewer; notes are exported on a Mac and then copied over.

---

## macOS

### Requirements

- macOS 12 Monterey or later (for the exporter; the viewer itself works on macOS 10.15+)
- Python 3.9 or later — pre-installed on all modern macOS versions
- [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter) by Konstantin Zaremski — not available via Homebrew

### 1. Install apple-notes-exporter

Download the latest `.zip` from the [Releases page](https://github.com/kzaremski/apple-notes-exporter/releases), then:

```bash
# Unzip and move to Applications
unzip AppleNotesExporter_v*.zip
mv "Apple Notes Exporter.app" /Applications/

# Symlink the embedded CLI so it is available in Terminal
sudo ln -sf \
  "/Applications/Apple Notes Exporter.app/Contents/SharedSupport/notes-export" \
  /usr/local/bin/notes-export
```

> Releases from v0.4 Build 5 onward are notarized. Older builds require a manual Gatekeeper exception in System Settings → Privacy & Security.

The exporter also needs **Full Disk Access** to read the Notes database. Grant it in System Settings → Privacy & Security → Full Disk Access.

### 2. Export your notes

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

### 3. Clone the repo

```bash
git clone https://github.com/anthonyjclarke/apple-notes-viewer.git
cd apple-notes-viewer
```

### 4. Launch

Double-click **`Launch Notes.command`** in Finder. macOS opens Terminal, the server starts, and your browser opens at `http://127.0.0.1:8765`.

On **first launch** you will see the Settings page. Click **Browse…**, navigate to your export folder, click **Select This Folder**, then **Save & Index Notes**. A progress bar tracks the index; the app opens automatically when done.

To stop the server, close the Terminal window.

### Keeping notes up to date

**Initial export** — the setup step above runs a full export with no `--incremental` flag. Run this once when you first set up the app; it may take several minutes for large note collections.

**Ongoing sync** — click **↻ Sync** in the sidebar footer. This runs:

```bash
notes-export export --format html --incremental --output ~/Documents/AppleNotes
```

The `--incremental` flag reads a watermark file that tracks the last-modified date of every exported note. Only notes newer than the watermark are re-exported, so repeated syncs are fast even with thousands of notes. After the export completes, the app re-indexes and the note list refreshes automatically.

**Force a full re-export** — if notes appear missing or out of date:

```bash
notes-export export --format html --reset-sync --output ~/Documents/AppleNotes
```

**iCloud notes** — sync whenever you want to pull in notes created or edited on another device. iCloud must have already synced those changes to this Mac before pressing ↻ Sync; the exporter reads the local Apple Notes database, not iCloud servers directly.

**On My Mac folders** — these notes live only on this Mac and are captured on initial export plus every subsequent sync. They will not appear in exports run on a different machine.

---

## Windows

### Requirements

- Windows 10 or later
- Python 3.9 or later — download from [python.org](https://www.python.org/downloads/); during install, check **"Add Python to PATH"**
- An exported notes folder copied from a Mac (see step 1 below)

### 1. Export on your Mac

Apple Notes export is macOS-only. You need a Mac with Apple Notes and `apple-notes-exporter` installed. Follow the **macOS** steps above to produce an export folder, then proceed here.

### 2. Copy the export folder to Windows

Transfer the entire export folder from your Mac to your Windows machine — USB drive, external drive, a shared network location, or a cloud service such as OneDrive.

**Example:** if your Mac exports to `~/Documents/AppleNotes`, copy that folder to `C:\Users\You\Documents\AppleNotes` on Windows. The internal folder structure must be preserved exactly.

### 3. Clone or copy the app files

```bat
git clone https://github.com/anthonyjclarke/apple-notes-viewer.git
cd apple-notes-viewer
```

Or download and extract the ZIP from GitHub if git is not installed.

### 4. Launch

Double-click **`Launch Notes.bat`**. Windows may show a SmartScreen warning — click **More info → Run anyway**. A terminal window opens, the server starts, and your browser opens at `http://127.0.0.1:8765`.

On **first launch** you will see the Settings page. Type or paste the path to your notes folder (e.g. `C:\Users\You\Documents\AppleNotes`), or click **Browse…** to navigate to it, then click **Save & Index Notes**.

To stop the server, close the terminal window.

### Keeping notes up to date

The **↻ Sync** button is not available on Windows — `apple-notes-exporter` runs only on macOS.

To get updated notes on Windows:

1. On your Mac, click **↻ Sync** in the app (or run `bash sync.sh` in Terminal).
2. Copy the updated export folder to Windows using the same method as the initial transfer.
3. The app re-indexes automatically on next launch, or click **Settings → Save & Index Notes** to re-index immediately without restarting.

---

## How it works

`server.py` is a zero-dependency Python HTTP server. On startup it binds immediately and kicks off indexing in a background thread — the browser opens right away and shows a loading screen until the index is ready. The index holds note titles, body text, hashtags, dates, and folder paths in memory for the session. Nothing is written to disk at runtime beyond `config.json`, which stores your chosen Notes folder path.

`app.html` is a single-file SPA that fetches from the server's JSON API and renders everything. No build step, no framework, no npm.

| File                     | Purpose                                                               |
|:-------------------------|:----------------------------------------------------------------------|
| `server.py`              | HTTP server — indexes notes, serves all API routes and static files   |
| `app.html`               | Single-page UI — layout, search, tag pills, PDF modal, lightbox       |
| `sync.sh`                | Sync script — wraps `notes-export export --incremental` (macOS only)  |
| `Launch Notes.command`   | Double-click launcher for macOS                                       |
| `Launch Notes.bat`       | Double-click launcher for Windows                                     |
| `config.json`            | Local config — your Notes folder path (gitignored, never committed)   |

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

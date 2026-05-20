# Apple Notes Viewer

A local web app for browsing and searching your Apple Notes exports. Runs entirely on your machine — no cloud, no accounts, no runtime dependencies beyond Python 3.

> **v2.5.0** — Built around [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter). See [CHANGELOG.md](CHANGELOG.md) for what changed.

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
notes-export export --format html --incremental --output ~/Documents/AppleNotes
```

This produces a folder structure like:

```
~/Documents/AppleNotes/
├── AppleNotesExportSyncWatermark.json
├── iCloud/
│   └── Notes/
│       ├── Holiday plans.html
│       └── Holiday plans (Attachments)/
└── On My Mac/
    └── Work/
        └── Meeting notes.html
```

The app needs the **parent** directory (e.g. `~/Documents/AppleNotes`) — the one that holds `iCloud/` and `On My Mac/` — not the folders inside.

> ⚠️ **Do not use a cloud-synced folder.** Point `notes_root` at a **plain local folder**, never one managed by **Syncthing, Dropbox, iCloud Drive, OneDrive, or Google Drive**. The exporter writes thousands of files and rewrites the manifest on every sync; a sync engine running on the same folder will replicate partial states and — critically — **propagate deletions made on another machine into this folder**, which looks exactly like catastrophic data loss. (It is not real loss: the export is a regenerable artefact and Apple Notes remains the source of truth — but it is avoidable pain.) If you need the export on another machine, copy it there *after* each export completes, or sync a different folder. As a safety net the app refuses to run attachment cleanup when it detects the folder is grossly out of sync with its own manifest.

> **Use `--incremental` from the very first export.** On an empty folder it performs a full export *and* writes `AppleNotesExportSyncWatermark.json`, the manifest that makes every subsequent ↻ Sync fast. If you omit it on the first run, no manifest is written, so your next Sync does a wasteful second full export before one is created.

#### Filename scheme

By default the exporter names files by **title only**, with **no date prefix** (`Holiday plans.html`). It can optionally prefix the note's **creation date** with `--add-date-prefix` (and `--date-format iso|us|eu`), producing `2024-06-15 Holiday plans.html`.

Both schemes work identically — the prefix is purely cosmetic, and the app never uses the filename for sorting or dates (see [How dates and times are handled](#how-dates-and-times-are-handled)). What matters is **consistency**: the incremental manifest keys on the exported path, so exporting under a *different* scheme than the existing files makes the exporter treat every note as new and silently duplicate the whole library (counts roughly double).

You no longer have to manage this by hand: **↻ Sync auto-detects the existing folder's scheme** (from the watermark, falling back to a scan of note files) and matches it — adding `--add-date-prefix --date-format iso` when the existing files are date-prefixed, or using the no-prefix default otherwise. An empty folder gets the no-prefix default. The only remaining rule: don't manually re-export an existing folder under the opposite scheme outside the app, and never use the `eu`/`us` date formats with this app (it matches on the ISO `YYYY-MM-DD` form).

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

**Initial export** — the setup step above already uses `--incremental`, so on the empty folder it does a full export and writes the watermark in one pass. Run it once when you first set up the app; it may take several minutes for large note collections.

**Ongoing sync** — click **↻ Sync** in the sidebar footer. This runs exactly:

```bash
notes-export export --format html --incremental --verbose --output <your folder>
```

The `--incremental` flag reads `AppleNotesExportSyncWatermark.json`, which records every exported note's path and modification date. Only notes that are new or changed since the last run are re-exported, so repeated syncs stay fast even with thousands of notes. After the export completes, the app re-indexes and the note list refreshes automatically. Sync automatically appends `--add-date-prefix --date-format iso` when it detects the existing files use a date prefix, so it stays consistent with your initial export (see [Filename scheme](#filename-scheme)).

**Replaced-image cleanup.** `apple-notes-exporter` is *additive* — if you shrink a note by swapping a large embedded image for a smaller screenshot, it writes the new attachment but leaves the original file orphaned in the note's `(Attachments)/` folder (it has no clean/prune option). After each Sync the app automatically removes attachment files a note no longer references. It also removes empty `(Attachments)` folders — the exporter creates these for every note and touches them on every incremental run even when nothing changed, which would otherwise make them show today's date in Finder. It is conservative by design: if anything about a folder is ambiguous it leaves that folder alone, never deleting note text or unrelated files. What was reclaimed is shown in the Sync Report.

**Force a full re-export** — if notes appear missing or out of date. `--reset-sync` deletes the manifest before exporting and is **only effective together with `--incremental`**:

```bash
notes-export export --format html --incremental --reset-sync --output ~/Documents/AppleNotes
```

If the folder has ended up with **duplicated notes** (counts roughly doubled — usually from a prefix/no-prefix scheme mix), the cleanest recovery is to delete the export folder's contents entirely — including `AppleNotesExportSyncWatermark.json` — then run the initial export command again. With no manifest present, `--incremental` rebuilds everything cleanly under a single scheme.

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

## How dates and times are handled

Understanding where the app gets its dates explains why the note ordering is what it is — and why the filename date prefix is irrelevant.

**Sort order — the note's last-edited time.** Notes are sorted newest-edited first, matching the order you see in Apple Notes on iPhone. The timestamp comes from the `<meta name="modified" content="D Mon YYYY at H:MM am/pm">` tag the exporter embeds in every HTML file (e.g. `8 May 2026 at 4:37 pm`). This value originates from Apple Notes' own database, so it is accurate and survives file copies, rsync, and OneDrive transfers.

**Fallback — file modification time (mtime).** If a note's `modified` meta tag is missing or unparseable, the app falls back to the file's on-disk mtime. The exporter sets mtime to the note's last-edit date, so this is usually still correct — but it is the *fallback*, because mtime can be rewritten by file copies or OS migration whereas the embedded meta tag cannot.

**The filename date prefix is cosmetic — never used for dates.** If your files are named `2024-06-15 Holiday plans.html`, that `2024-06-15` is the note's *creation* date added by `--add-date-prefix`. The app strips a leading `YYYY-MM-DD ` prefix purely so it does not pollute the displayed title or tag extraction. It is **never** parsed as a date or used for sorting. This is why the no-prefix and date-prefix schemes display and sort identically — and why mixing them only causes duplicate files, never different ordering (see [Filename scheme](#filename-scheme)).

**The "1 Jan 2001" cluster at the bottom is normal.** Some notes — typically very old, imported, or migrated ones — have no valid date in Apple Notes' database. Apple stores these with a 1 January 2001 timestamp (the Apple Cocoa epoch), so the exporter writes `<meta name="modified" content="1 Jan 2001…">` and the app sorts them together at the very bottom as one undated group. In large collections this can be a sizeable cluster. It reflects Apple Notes' own missing metadata — it is not a bug in the exporter or the viewer, and there is no date information to recover.

**Time zones.** The exporter writes local wall-clock time with no zone offset; the app parses and displays it verbatim. Dates therefore reflect the time zone of the Mac that produced the export.

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

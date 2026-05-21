# Apple Notes Viewer

A local web app for browsing and searching your Apple Notes exports. Runs entirely on your machine — no cloud, no accounts, no runtime dependencies beyond Python 3.

> **v2.7.0** — Built around [`apple-notes-exporter`](https://github.com/kzaremski/apple-notes-exporter). See [CHANGELOG.md](CHANGELOG.md) for what changed.

---

<!-- SCREENSHOT: Full three-column UI in light mode — sidebar with folders and tag pills, note list, note content open -->

---

## Features

- **Three-column layout** — sidebar, note list, and content pane; mirrors the Apple Notes desktop experience
- **Full-text search** — searches complete note body text, not just visible snippets; results highlighted as you type
- **Folder navigation** — browse a single Apple Notes folder or search across all notes with one click
- **Tag pills** — detects `#hashtags` from note text and filenames, matching Apple Notes exactly (including digit-first tags like `#10SmallSt` and short tags like `#AI`); displayed as clickable pill chips
- **Sort by date or size** — notes sorted newest-edited first by default; a toggle in the list panel switches to largest-first, with size-bucket group headers; each note shows a compact file-size badge colour-coded by tier (amber ≥ 1 MB, red ≥ 5 MB)
- **Attachment indicator and filter** — notes that have an `(Attachments)` folder show a paperclip icon in the title row; a **Has Attachments** filter pill in the sidebar narrows the list to those notes only, combining with any active folder, tag, or search filter
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
3. The app re-indexes automatically on next launch, or click the gear icon → **Save & Index Notes** to re-index immediately without restarting. (If you only want to check the configured path, click **← Back** to return without re-indexing.)

---

## How dates and times are handled

Understanding where the app gets its dates explains why the note ordering is what it is — and why the filename date prefix is irrelevant.

**Sort order — the note's last-edited time.** Notes are sorted newest-edited first, matching the order you see in Apple Notes on iPhone. The timestamp comes from the `<meta name="modified" content="D Mon YYYY at H:MM am/pm">` tag the exporter embeds in every HTML file (e.g. `8 May 2026 at 4:37 pm`). This value originates from Apple Notes' own database, so it is accurate and survives file copies, rsync, and OneDrive transfers.

**Fallback — file modification time (mtime).** If a note's `modified` meta tag is missing or unparseable, the app falls back to the file's on-disk mtime. The exporter sets mtime to the note's last-edit date, so this is usually still correct — but it is the *fallback*, because mtime can be rewritten by file copies or OS migration whereas the embedded meta tag cannot.

**The filename date prefix is cosmetic — never used for dates.** If your files are named `2024-06-15 Holiday plans.html`, that `2024-06-15` is the note's *creation* date added by `--add-date-prefix`. The app strips a leading `YYYY-MM-DD ` prefix purely so it does not pollute the displayed title or tag extraction. It is **never** parsed as a date or used for sorting. This is why the no-prefix and date-prefix schemes display and sort identically — and why mixing them only causes duplicate files, never different ordering (see [Filename scheme](#filename-scheme)).

**The "1 Jan 2001" cluster at the bottom is normal.** Some notes — typically very old, imported, or migrated ones — have no valid date in Apple Notes' database. Apple stores these with a 1 January 2001 timestamp (the Apple Cocoa epoch), so the exporter writes `<meta name="modified" content="1 Jan 2001…">` and the app sorts them together at the very bottom as one undated group. In large collections this can be a sizeable cluster. It reflects Apple Notes' own missing metadata — it is not a bug in the exporter or the viewer, and there is no date information to recover.

**Time zones.** The exporter writes local wall-clock time with no zone offset; the app parses and displays it verbatim. Dates therefore reflect the time zone of the Mac that produced the export.

**Note size.** The file-size badge shown in the note list is the size of the exported HTML file. Because the exporter encodes all embedded images as inline base64 in the HTML, this is a faithful proxy for the total weight of the note's content. Notes saved from the iPhone share sheet (e.g. "Saved Photo") can be several megabytes. Use the **↓ Size** sort toggle to find your largest notes quickly — useful for identifying notes to trim before a device sync.

---

## Deleting notes and managing stale exports

Understanding how note deletion works in this app requires understanding three things first:

1. **Apple Notes is the source of truth.** This app never modifies Apple Notes. Anything you delete here only affects the export folder.
2. **The exporter is additive.** `apple-notes-exporter` writes new files and updates changed ones, but never deletes files on its own. Files only disappear if this app removes them.
3. **The incremental exporter trusts the watermark.** `AppleNotesExportSyncWatermark.json` records, per note: UUID, `modificationDate`, and `exportedPath`. On the next sync, the exporter compares each note's live `modificationDate` against the watermark. If they match, the note is **skipped** — even if the note has moved to a different folder inside Apple Notes (most importantly, into Recently Deleted).

Everything below follows from those three facts.

### The four states a note can be in

| State in Apple Notes | State on disk | What the viewer shows |
|:--|:--|:--|
| Exists in a normal folder | HTML in `iCloud/Notes/…` | Regular note |
| Moved to Recently Deleted (within 30-day window) | HTML in `iCloud/Recently Deleted/…` | 🗑 Recently Deleted pill in the list, red warning banner in the content pane |
| Permanently deleted (cleared from Recently Deleted) | HTML still in `iCloud/Notes/…` from a previous export | Regular note (stale — does not actually exist in Apple Notes) |
| Removed via the viewer's 🗑 trash icon | HTML and `(Attachments)` folder deleted; watermark entry removed | Gone from the viewer |

The third state — *permanently deleted in Apple Notes but still on disk* — is the source of "drift". The exporter cannot remove the file, so the app provides multiple ways to detect and clean it up.

### Recently Deleted notes are visible and marked

Notes you have moved to Recently Deleted in Apple Notes appear in the viewer — in the note list, in All Notes, and in search — but are visually distinguished from regular notes:

- A red **🗑 Recently Deleted** pill badge appears below the note title in the list
- The note title is shown in a muted colour
- The Recently Deleted folder in the sidebar carries a 🗑️ icon
- Opening the note shows a red warning banner at the top: *"This note has been deleted from Apple Notes and will be permanently removed within 30 days. It can still be restored from Recently Deleted in Apple Notes."*

These notes can still be restored from Recently Deleted in Apple Notes before the 30-day window closes. Removing them in the viewer (via the 🗑 trash icon) only deletes the export file — Apple Notes is untouched.

> **Important limitation:** the incremental exporter does **not** detect when a note moves between folders inside Apple Notes if its `modificationDate` hasn't changed. So a note that was already exported as `iCloud/Notes/Foo.html`, then moved to Recently Deleted in Apple Notes, may continue to show as a regular note in the viewer until a **Force Full Re-export** is run. This is the most common reason to use that option.

### Detection signals the app provides

After every sync, the app uses three signals to identify stale or misplaced notes:

| Signal | When it fires | What it identifies | Precision |
|:--|:--|:--|:--|
| **Deleted from Apple Notes** card | Exporter emits `Deleted (no longer in Notes): <path>` lines in `--verbose` | Notes permanently deleted from Apple Notes since the last sync | Exact paths — confirmed by the exporter |
| **Drift warning banner** | Indexed HTML count exceeds Apple Notes' live total by ≥ 10 notes or ≥ 2% | Accumulated stale files from long-ago deletions | Count-based — does not name individual files |
| **Stale HTML files** card | A `--reset-sync` (Force Full Re-export) was run and on-disk HTML doesn't match the fresh watermark | Both stale files AND old copies of notes that moved between folders | Exact paths — the most authoritative signal |

The third signal is the most powerful but only runs on demand because it requires a full re-export. The first two run on every normal sync.

### How to remove notes from the export folder

Three options, from least to most invasive:

**1. The viewer's 🗑 trash icon (single note).**  Hover the date bar at the top of any open note and click 🗑 → **Remove**. This:

- Deletes the HTML file
- Deletes the `(Attachments)` folder if one exists
- **Removes the matching watermark entry** so the next sync re-exports the note if it still exists in Apple Notes
- Removes the note from the viewer immediately (no re-index)

If you delete a note here that *still exists in Apple Notes*, the next ↻ Sync will re-export it and it will reappear. Removal is only permanent for notes you confirm are already gone from Apple Notes.

**2. The Sync Report's "Deleted from Apple Notes" card (bulk, exporter-confirmed).** Appears automatically after any sync where the exporter flagged notes as deleted. Each row has a **Remove** button; **Remove all** clears them in one click. These are the safest bulk removals — the exporter has confirmed each note is gone from Apple Notes.

**3. ⟲ Force Full Re-export (comprehensive).** Available in three places: the **⟲ Force Full Re-export** link in the sidebar footer, the **⟲ Force Full Re-export** button in the drift warning banner, and (implicitly) the equivalent command-line invocation. This:

- Asks for confirmation before proceeding
- Passes `--reset-sync` to the exporter, which deletes the watermark first
- Re-exports every note from Apple Notes to its **current** location (correctly placing notes that have moved to Recently Deleted)
- After export, scans on-disk HTML files against the fresh watermark to identify stale files
- Shows a **Stale HTML files** card in the Sync Report with per-file **Remove** and bulk **Remove all** buttons
- Takes substantially longer than a normal sync — several minutes for a large library

This is the only way to bring the export folder fully back in sync with Apple Notes. Use it after deleting many notes from Apple Notes, after the drift warning appears, or whenever you want to be certain the viewer reflects the current state.

### Permutations — what happens when you…

Every common scenario you might run into:

| Action | What happens to the HTML on disk | What you should do |
|:--|:--|:--|
| Edit a note in Apple Notes, then ↻ Sync | Exporter re-writes the HTML with new content; old `(Attachments)` files for non-image attachments are pruned automatically | Nothing — works as expected |
| Move a note to Recently Deleted in Apple Notes, then ↻ Sync | **Nothing** — `modificationDate` is unchanged, so incremental sync skips the note; HTML stays at its old `iCloud/Notes/…` location | Run ⟲ Force Full Re-export to relocate the HTML to `iCloud/Recently Deleted/…` and have the Recently Deleted badge appear |
| Permanently delete a note in Apple Notes (clear from Recently Deleted), then ↻ Sync | Exporter emits `Deleted (no longer in Notes): <path>`; HTML stays on disk | Click **Remove** in the Sync Report's "Deleted from Apple Notes" card |
| Delete a note via the viewer's 🗑 trash icon (note still exists in Apple Notes) | HTML and `(Attachments)` deleted; watermark entry removed | Next ↻ Sync re-exports it because the watermark entry is gone |
| Delete a note via the viewer's 🗑 trash icon (note already gone from Apple Notes) | HTML and `(Attachments)` deleted; watermark entry removed | Stays gone — exporter has nothing to re-write |
| Delete many notes in Apple Notes at once, then ↻ Sync | Some appear as Recently Deleted (those with changed `modificationDate`); others remain in their old location | Run ⟲ Force Full Re-export to relocate everything correctly |
| Apple Notes' 30-day Recently Deleted window expires on a note | Exporter emits `Deleted (no longer in Notes):` on next sync; HTML at `iCloud/Recently Deleted/…` stays on disk | Click **Remove** in the "Deleted from Apple Notes" card |
| Restore a note from Recently Deleted in Apple Notes | Apple Notes updates `modificationDate`; next ↻ Sync re-exports it to its restored location; old `iCloud/Recently Deleted/…` copy stays on disk | Run ⟲ Force Full Re-export to clean up the old copy |

### Summary — when to use Force Full Re-export

Run **⟲ Force Full Re-export** whenever:

- You've moved any notes to Recently Deleted in Apple Notes and want them to appear with the badge in the viewer
- The Sync Report shows a drift warning
- You've restored notes from Recently Deleted and old copies remain on disk
- You want to be certain the viewer matches Apple Notes exactly (e.g. before sharing the export folder, or after a long period without a full re-export)

Avoid running it for trivial reasons — it re-exports every note and can take several minutes on a large library.

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

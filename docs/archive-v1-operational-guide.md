# Notes Viewer — Operational Guide (v1 Archive)

> **ARCHIVED — v1.0 only. This document does not apply to v2.0.**
>
> v2.0 is a complete rewrite built around [`apple-notes-exporter`](https://github.com/nicholasstephan/apple-notes-exporter).
> The folder layout, setup workflow, sync process, and architecture described below
> are all superseded. Refer to [README.md](../README.md) for setup and
> [CLAUDE.md](../CLAUDE.md) for architecture.
>
> This file is retained as a reference for the v1.0 Falcon Notes Exporter-based release.

---

A local web application for browsing and searching Apple Notes exports produced by
[Falcon Notes Exporter](https://falcon.star-lord.me/exporter). Runs entirely on your Mac —
no cloud, no accounts, no dependencies beyond Python 3.

---

## Architecture

Three files do all the work:

| File                    | Purpose                                                                 |
|:------------------------|:------------------------------------------------------------------------|
| `server.py`             | Python HTTP server — indexes notes on startup, serves all API routes    |
| `app.html`              | Single-page UI — Apple Notes-style layout, search, tag sidebar          |
| `Launch Notes.command`  | Double-click launcher — kills old instance, starts server, opens browser |

The server reads your export folder at startup, builds an in-memory index (titles,
dates, body text, hashtags), and holds it for the session. Nothing is written to disk
at runtime.

### Date and sort order

Notes are sorted by **last-edited date**, matching Apple Notes on iPhone. Falcon Notes
Exporter preserves the original last-edit timestamp from Apple Notes by setting each
exported `.html` file's modification time (`mtime`) to that date. The server reads the
file `mtime` directly — not the date in the filename.

The `{DD-MM-YYYY}` suffix in the filename is the note's **creation date** and is not
used by the app.

---

## Folder Layout

```
AppleNotes/                    ← project root
├── server.py
├── app.html
├── Launch Notes.command
├── NOTES_VIEWER.md            ← this file
├── .claude/
│   └── launch.json            ← Claude Code preview config (ignore)
└── Notes/                     ← export container (add account folders here)
    ├── On My Mac/             ← export from "On My Mac" account
    │   ├── Note Title-DD-MM-YYYY.html
    │   ├── images/
    │   │   └── <UUID>.png     ← images embedded in notes
    │   └── attachments/
    │       └── <UUID>.pdf     ← PDF attachments
    └── iCloud/                ← export from iCloud account (if applicable)
        ├── Note Title-DD-MM-YYYY.html
        ├── images/
        └── attachments/
```

The `<title>` tag inside each HTML file is used as the display title — it preserves
characters like `/` that filenames cannot contain.

---

## Initial Setup

Follow these steps the first time you set up the app, or when adding a new Notes account.

### Step 1 — Install Falcon Notes Exporter

Download and install [Falcon Notes Exporter](https://falcon.star-lord.me/exporter).
It is a free Mac app that reads directly from Apple Notes and exports to HTML.

### Step 2 — Export your notes

Open Falcon Notes Exporter. It will show all your Notes accounts and folders. Select
the account (e.g. "On My Mac") and all folders you want to include, then click
**Export**. When prompted for format, choose **HTML**.

Falcon will ask where to save. Choose any convenient location (e.g. your Desktop).
It will create a folder named after your account — typically:

```
On My Mac/
```

The folder contains one `.html` file per note, plus `images/` and `attachments/`
subdirectories.

### Step 3 — Place the export folder

The `Notes/` folder inside the project root is the container for all export data.
It is tracked in git as an empty directory (via `.gitkeep`) but its contents are
gitignored — your notes are never committed.

If `Notes/` is missing for any reason, create it:

```bash
mkdir ~/PlatformIO/Projects/AppleNotes/Notes
```

Move the exported folder from wherever Falcon saved it into `Notes/`:

```bash
mv ~/Desktop/"On My Mac" ~/PlatformIO/Projects/AppleNotes/Notes/
```

The resulting path should be:

```
~/PlatformIO/Projects/AppleNotes/Notes/On My Mac/
```

If you have a second account (e.g. iCloud), export it separately and place that
folder alongside the first:

```
Notes/
├── On My Mac/
└── iCloud/
```

### Step 4 — Launch

Double-click `Launch Notes.command` in Finder. The server indexes all HTML files
inside `Notes/` and opens the app in your browser automatically.

---

## Launching

Double-click `Launch Notes.command` in Finder. macOS will open Terminal, the server
will start, and Safari/Chrome will open at `http://127.0.0.1:8765` automatically.

**To stop:** close the Terminal window the launcher opened.

**Port in use?** The launcher kills any existing instance on port 8765 before
starting, so a stale process should not block a fresh launch. If it does:

```bash
lsof -ti tcp:8765 | xargs kill -9
```

---

## UI Reference

### Three-column layout

```
┌──── Sidebar ────┬──── Note List ───────┬──── Note Content ─────────┐
│ Notes      ☀️ ◉ │ 🔍 Search            │ Wednesday 8 May 2024       │
│                 │ 980 notes            │                            │
│ ON MY MAC       │ 2024                 │ Note Title                 │
│ 📋 All Notes 980│ ┌──────────────────┐ │                            │
│ 📁 On My Mac 800│ │ Title    12 Nov  │ │ Note body text…            │
│ 📁 iCloud    180│ │ snippet…         │ │                            │
│                 │ └──────────────────┘ │ [images render inline]     │
│ TAGS            │ 2023                 │                            │
│ # GPS        14 │ ┌──────────────────┐ │                            │
│ # Pivotal     4 │ │ Title    6 Dec   │ │                            │
│ # AppMod…     2 │ │ snippet…         │ │                            │
└─────────────────┴──────────────────────┴────────────────────────────┘
```

The note list column width is adjustable — drag the divider between the list and
content panels. Your preferred width is saved and restored automatically.

### Sidebar

- **All Notes** — shows every note across all folders, sorted by last-edited date.
- **Folder items** — scopes the list to that folder.
- **Tags section** — each `#tag` found in note bodies that appears in ≥ 2 notes.
  Clicking a tag populates the search box and searches across all folders.

### Search

| Behaviour                 | Detail                                                          |
|:--------------------------|:----------------------------------------------------------------|
| Scope                     | Searches full body text on the server, not just visible snippets |
| Minimum query length      | 2 characters                                                    |
| Debounce                  | 250 ms — results appear as you type                             |
| Folder scoping            | Searches the selected folder by default                         |
| Search all notes pill     | Appears below the search box when a specific folder is selected; click to expand search to all folders |
| Highlight                 | Matching text is highlighted in yellow in both title and snippet |

**Keyboard shortcuts:**

| Key          | Action                                     |
|:-------------|:-------------------------------------------|
| `/` or `⌘F`  | Focus the search box                       |
| `↑` / `↓`   | Move between notes in the list             |
| `Escape`     | Clear search / deselect tag / close lightbox |

### Note content

Images embedded in notes render inline. Click any image to open it full-screen
(lightbox). Click outside or press `Escape` to close. PDF attachments appear as
links that open in a new tab.

### Dark mode

The sun/moon toggle in the top-left of the sidebar switches between light and dark.
Your preference is saved to `localStorage` and persists across sessions.

---

## Updating the Notes Export

When you run a fresh export from Falcon Notes Exporter, follow these steps.

### Step 1 — Export from Falcon

Open Falcon Notes Exporter. Select the account and folders you want and export to
HTML. Falcon will produce a folder named after your account, e.g.:

```
On My Mac/
```

### Step 2 — Stop the server

Close the Terminal window from `Launch Notes.command`, or run:

```bash
lsof -ti tcp:8765 | xargs kill -9
```

### Step 3 — Replace the export folder

Delete the old account folder and move the new one into `Notes/`:

```bash
rm -rf ~/PlatformIO/Projects/AppleNotes/Notes/"On My Mac"
mv ~/Desktop/"On My Mac" ~/PlatformIO/Projects/AppleNotes/Notes/
```

The resulting path must be:

```
~/PlatformIO/Projects/AppleNotes/Notes/On My Mac/
```

The folder name must match exactly. If you are updating only one account, leave any
other account folders (e.g. `iCloud/`) untouched.

> The `Notes/` directory itself should always remain in place — only replace the
> account subfolder(s) inside it. If `Notes/` is ever accidentally deleted, recreate
> it with `mkdir ~/PlatformIO/Projects/AppleNotes/Notes` before relaunching.

### Step 4 — Relaunch

Double-click `Launch Notes.command`. The server re-indexes from scratch on startup
and prints a summary:

```
Indexing notes… 1240 notes · 2 folder(s) · 6 tags.
  → http://127.0.0.1:8765
```

The note count, folder count, and tag count will reflect the new export.

---

## Multiple Accounts

The server indexes all `.html` files recursively inside `Notes/`. Each subfolder
becomes a separate entry in the sidebar, grouped by account (the first path component).

To add a second account, export it separately from Falcon and place its folder
alongside the first inside `Notes/`:

```
Notes/
├── On My Mac/     ← first account
│   ├── images/
│   └── *.html
└── iCloud/        ← second account
    ├── images/
    └── *.html
```

Both will appear as separate folders in the sidebar after a relaunch.

---

## Tag Detection

The server scans every note body at index time and extracts strings matching:

```
(?:^|\s)#([A-Za-z][A-Za-z0-9]{2,})
```

Rules applied:

- The `#` must follow whitespace or be at the start of a line — this eliminates
  URL fragment anchors (e.g. `example.com/page#section`).
- The tag must start with a letter — eliminates `#123` and numeric anchors.
- Minimum three characters total — eliminates `#ok`.
- A blocklist removes known HTML/URL noise: `heading`, `slide`, `gid`, `vis`,
  `showing`, `sthash`, `providers`, `dashboard`, `exec`.
- Tags appearing in only **one** note are hidden from the sidebar (likely noise).

**What this means in practice:** Apple Notes `#tags` typed inline in note text are
detected. Tags are **not** exported as structured metadata by Falcon — they exist
only as plain text. Searching `#GPS` in the search box has the same effect as
clicking the tag in the sidebar.

To search for a tag manually: type `#tagname` in the search box. The full-body
search will find every note containing that string.

---

## Troubleshooting

### Browser shows a spinner and nothing loads

The server is not running. Double-click `Launch Notes.command`.

### "Port in use" error in Terminal

Another instance is running. The launcher kills it automatically, but if it fails:

```bash
lsof -ti tcp:8765 | xargs kill -9
```

Then re-launch.

### Images not showing in a note

The image UUID referenced in the HTML is missing from the `images/` folder. This
can happen if Falcon skipped attachments during export. Re-export with attachments
enabled and replace the export folder.

### A tag you expect is not in the sidebar

Either it appears in only one note (filtered out), or the `#` in the note is not
preceded by whitespace (e.g. it is inside a URL). You can still search for it
manually by typing `#tagname` in the search box.

### Notes from a different export are missing

The server only indexes `*.html` files inside `Notes/`. If you replaced only part
of the export, or an account folder has a different name, those notes will not appear.
Always replace the entire account folder and relaunch.

### The app worked before but an account folder was renamed

Open `server.py` and check line 14:

```python
NOTES_ROOT = BASE_DIR / "Notes"
```

`NOTES_ROOT` points to the container folder (`Notes/`). Account subfolders inside it
are discovered automatically — you only need to update this line if you rename the
container itself.

---

## Technical Reference

| Item                    | Value                                                        |
|:------------------------|:-------------------------------------------------------------|
| Server port             | `8765` (hardcoded in `server.py`)                            |
| Python requirement      | Python 3.9 or later (tested on 3.11.7)                       |
| External dependencies   | None — stdlib only (`http.server`, `html.parser`, `json`)    |
| Sort order              | Last-edited date (file `mtime` set by Falcon on export)      |
| Tag minimum occurrences | 2 notes (configurable in `server.py` — search `if c >= 2`)   |
| Search minimum length   | 2 characters (configurable in `app.html` — search `< 2`)     |
| Snippet length          | 280 characters of body text                                  |
| Theme persistence       | `localStorage` key `notes-theme`                             |
| List column width       | `localStorage` key `notes-list-w`                            |

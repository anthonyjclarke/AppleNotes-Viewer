# Apple Notes Viewer — User Test Plan (v3.0.0)

High-level smoke test to run before tagging v3.0 as released. Run on the
machine that produced the most recent real export, not a clean fixture —
covers the bulk of edge cases (long-titled notes, image-only notes, notes
with `&` in titles, Recently Deleted, etc.).

## Setup

1. `git pull` and confirm `git log -1` shows the v3.0 commit.
2. From the project root: `python3 server.py` (or double-click
   `Launch Notes.command`).
3. Browser opens at `http://127.0.0.1:8765`. Expect a brief loading
   overlay; library indexes within ~15 s for ~1,800 notes.
4. **Memory baseline** — note the Python process RSS via Activity Monitor
   or `ps -o rss= -p $(pgrep -f server.py)`. Should be **lower** than
   v2.7 baseline by 30–50% for libraries with image-heavy notes.

If you intend to test the in-app **↻ Sync**, grant Full Disk Access to
Terminal *before* starting the server.

---

## Smoke checklist

Each item should take under 30 seconds. If any one fails, stop and
investigate before continuing — later items often depend on earlier state.

### 1. First-paint baseline
- [ ] App loads to the three-column layout
- [ ] Sidebar shows folder list grouped by account (`iCloud`, etc.)
- [ ] At least one folder shows the 🗑️ icon (Recently Deleted)
- [ ] Sidebar shows the **Filters** section (above Tags) with the
      **📎 Has Attachments** pill
- [ ] Sidebar shows the **Tags** section with at least the **All Tags**
      pill plus any real tags
- [ ] Note list renders with date group headers (Today, Yesterday,
      Previous 7 Days, Previous 30 Days, year groups)
- [ ] Each row shows: title, size badge (colour-coded), date badge;
      paperclip icon on rows with attachments
- [ ] Tiny notes (< 100 KB) show their size badge in a very subtle
      grey (near-invisible)
- [ ] Empty (zero-byte) notes show **no** size badge

### 2. Search
- [ ] Type `recipe` (or any term you know is present) in the search box —
      results render within ~300 ms with highlighted matches in titles
      and snippets
- [ ] Switch to a specific folder, then type a query — results scope to
      that folder
- [ ] Click **Search all notes** pill — results expand to all folders;
      pill shows pressed state
- [ ] Clear search (`Esc` or × icon) — list returns to current folder's
      notes
- [ ] **Tag search:** click a tag pill — query box fills, results show
      across all folders, tag pill is highlighted
- [ ] Click **All Tags** — query clears, folder selection restored

### 3. Sort by date / size
- [ ] Default sort is **↓ Date**, group headers are date buckets
- [ ] Click **↓ Date** → toggles to **↓ Size**, button is highlighted,
      group headers change to size buckets (`5 MB and above`,
      `1 – 5 MB`, `100 KB – 1 MB`, `Under 100 KB`)
- [ ] Largest notes appear first
- [ ] **Reload the page** (Cmd-R) — sort mode is **preserved** as
      Size (was reset on reload in v2.7)
- [ ] Toggle back to Date — change persists across reload

### 4. Attachment filter
- [ ] Click **📎 Has Attachments** — list narrows to notes with the
      paperclip icon, pill shows pressed state, count says
      `N notes with attachments`
- [ ] Switch folders — filter remains active
- [ ] Type a search query — filter ANDs with search
- [ ] **Reload the page** — filter is **preserved**
- [ ] Click the pill again — full list returns

### 5. Open a note
- [ ] Click any note — content pane loads within ~200 ms
- [ ] Title, content, embedded images render correctly
- [ ] Click an image — lightbox opens; click again or press Esc — closes
- [ ] If the note has a `#hashtag` in the title, no duplicate `<h1>` is
      visible

### 6. Image-only notes
- [ ] Find a "Saved Photo" note (or any note whose body is just an
      image)
- [ ] Title and image both render — image is **not** hidden (regression
      test for the v2.7 fix)

### 7. PDF preview
- [ ] Open a note with a PDF attachment — the PDF embeds inline in the
      content pane (no card to click)
- [ ] If a note has a PDF inside an attachment folder with a `#` in its
      name, the click still opens the inline iframe (no `%23` corruption)

### 8. Recently Deleted
- [ ] Folder shows in the sidebar with 🗑️ icon
- [ ] Notes inside show the red `🗑 Recently Deleted` pill in the list
- [ ] Note title in the list is muted/grey
- [ ] Open one — red banner at the top reads "This note has been deleted
      from Apple Notes…"
- [ ] These notes also appear in **All Notes** and **search results**
      with the same badge

### 9. Delete a note from the viewer
- [ ] Open any non-critical note
- [ ] Hover the date bar at the top — 🗑 icon appears
- [ ] Click 🗑 → inline confirm shows "Remove from viewer only? / Cancel
      / Remove"
- [ ] Click **Cancel** — confirm dismisses, note stays open
- [ ] Click 🗑 → **Remove** — note disappears from list, content pane
      advances to next note, sidebar counts update **without** a full
      re-index
- [ ] If the note still exists in Apple Notes: run ↻ Sync — note
      re-appears (watermark entry was correctly removed)

### 10. Settings — view + back
- [ ] Click ⚙️ in the sidebar header — Settings page opens
- [ ] Current folder path is shown in the input
- [ ] **← Back** button appears next to **Save & Index Notes**
- [ ] Click ← Back — return to the viewer, **no re-index runs**
- [ ] Re-open Settings, click Browse… — folder picker overlay opens,
      navigation works (parent/child)

### 11. Settings — change path
- [ ] In Settings, type a real folder path → **Save & Index Notes** →
      indexing runs, auto-returns to the viewer
- [ ] **Invalid-path case:** in Settings, type a deliberately-wrong path
      (e.g. `/tmp/does-not-exist`) → **Save** — error shown, no index
      starts, and the existing saved config is not overwritten
- [ ] **Stale-config case:** before launch, put a missing path in
      `config.json` → start the server → Settings opens with that stale path
      shown (`configured_root` fallback)
- [ ] Type the correct path back → **Save** — works again

### 12. ↻ Sync (macOS only)
- [ ] Click ↻ Sync — Sync Report modal opens immediately in **live
      mode** with a pulsing ● Live badge and streaming output
- [ ] The × close button is **disabled** during the live phase
- [ ] When export completes, modal transitions to **Re-indexing…**
- [ ] When re-index completes, modal shows phase cards: **Export**,
      **Attachment cleanup**, **Re-index**
- [ ] If the exporter deleted any notes: **Deleted from Apple Notes**
      card with Remove / Remove all
- [ ] If drift was detected: yellow banner with **⟲ Force Full Re-export**
      button
- [ ] Click **Done — return to notes** — modal closes, sidebar + list
      refresh
- [ ] Click the **Log** button in the sidebar footer — terminal-style
      log re-opens (no phase cards in this view)

### 13. ↻ Sync — benign no-op
- [ ] Click ↻ Sync again *immediately* (no notes have changed) — sync
      runs, exits with the "All notes are up to date" message, completes
      successfully (**no** false "Sync failed")

### 14. ⟲ Force Full Re-export
- [ ] Click **⟲ Full Re-export** in the sidebar footer — confirmation
      dialog appears, lists what will happen
- [ ] Confirm → live modal opens; export runs against the wiped watermark
- [ ] When complete, **Stale HTML files on disk** card appears if any
      stale files were found (only after `--reset-sync`)
- [ ] Each row has Remove + a bulk Remove all
- [ ] Modal header reads `⟲ Forced full re-export` (not `Incremental
      sync`)

### 15. Modal force-close (rare)
*(Skip unless you have a way to hang the exporter — only test if
applicable.)*
- [ ] If a sync hangs with no new output for ≥ 60 s, the × close button
      re-enables and shows "Sync appears stuck — click to dismiss"

### 16. Keyboard + accessibility
- [ ] Press `/` or `⌘F` outside the search box — focus jumps to search
- [ ] `↑`/`↓` while focused outside search — moves through note list
- [ ] `Esc` — closes PDF modal first → lightbox → clears search → closes
      About modal (priority order)
- [ ] Tab through the header — focus rings appear on Settings, About,
      theme toggle, search box, folder items, sort toggle, attachment
      filter
- [ ] In dev tools, inspect the **theme toggle** and **sort toggle** —
      both have `aria-pressed` reflecting current state
- [ ] Open About modal → focus moves to the title; close → focus
      returns to the info button

### 17. Light / dark
- [ ] Click the theme toggle — colour scheme flips immediately
- [ ] Reload — preference persists
- [ ] All controls (size badges, sort toggle, attachment pill, filter
      pill, modals) render correctly in both themes

### 18. Resize panels
- [ ] Drag the sidebar/list divider — list panel resizes
- [ ] Drag the list/content divider — content panel resizes
- [ ] Reload — widths persist

### 19. Note size identification (v3.0 perf win)
- [ ] Sort by ↓ Size — confirm the top entries are recognisable as your
      largest notes
- [ ] Memory check: re-measure server RSS — should be lower than the
      pre-3.0 baseline; the difference is most visible on libraries
      with multiple 5 MB+ image notes

### 20. Cache invalidation
- [ ] In a Chrome dev tools Network tab, click between folders rapidly —
      `/api/notes` should **not** fire on every click (after the first
      one for each folder, the cache short-circuit returns instantly)
- [ ] Run ↻ Sync — observe `/api/index-status` returns an incremented
      `index_version`; subsequent folder clicks correctly refetch
      `/api/notes` once each (cache invalidated by version change)

---

## Acceptance criteria for v3.0 release

- All P0 (size sort, attachment filter, deletion handling) items pass
- All P1 perf items show measurable improvement
  (size sort is responsive; memory is lower; no folder-click jank)
- No regression in PDF rendering, Recently Deleted display, or sync flow
- Image-only "Saved Photo" notes render correctly
- No new browser-console errors during normal use

When all green: tag `v3.0.0`, merge `dev → main`, push tag.

## Known limitations not in scope for 3.0

- No virtualisation in the note list — 1,800+ DOM nodes is still the
  upper bound; very weak hardware may stutter while scrolling fast
- No full focus trap in modals — Tab from inside a modal can leak to
  background content (we autofocus on open but don't fence Tab cycling)
- No screenshots in README yet (placeholder comments remain)

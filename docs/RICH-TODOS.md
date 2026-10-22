# TetherBot rich todos (v0.1.x step 2)

Status: approved by the owner. Build it. Goal: make TetherBot a todo tracker good enough to replace an older single-repo todo app, while bots stay the only ones who create and edit items. The desktop reads, filters, searches, opens, and checks off. It never edits item text.

## 1. What "good enough to switch" means

The cutover to TetherBot as the only todo tracker happens when all of these work on the owner's desktop:

1. Color-coded tag chips on every todo.
2. Due-date chips colored by urgency, plus a created date.
3. Priority shown on every todo.
4. Open any todo to read the whole thing rendered as Markdown.
5. Filter by tag and by quick views (All, Mine, Bots, Waiting, Today).
6. Keyword search across title, body, and tags.
7. Done from either the popup or the detail view, with the existing hide-on-tap and webhook flow.

Editing, adding, deleting, snoozing to a date, and pinning are done by asking the bot in chat. They are out of scope for the desktop.

## 2. Where each piece lives

The top-bar popup stays glanceable. The rich view is a separate window.

| Surface | Job |
|---|---|
| Top-bar popup (GNOME Shell extension) | Counts, the next few todos with chips, a search box, Done, and an "Open TetherBot" button |
| TetherBot window (new, GTK4 + libadwaita) | Full list, quick views, tag filter, search, sort, and a Markdown detail pane |
| Bridge (existing daemon) | Owns the data, exposes it over D-Bus, and launches the window |

Why a separate window: the Shell popup is narrow, can't host long scrolling Markdown well, and extensions on extensions.gnome.org should not spawn processes. The extension asks the bridge over D-Bus to open the window (`OpenWindow(item_key)`); the bridge launches it. The window is its own process and also talks only to the bridge over D-Bus. It holds no secrets and makes no network calls.

GTK4, libadwaita, and PyGObject are already on the target Fedora 44 desktop.

## 3. Feed schema additions (`tetherbot/1`, backward compatible)

All new fields are optional. Old desktops ignore them.

Per item:

| Field | Type | Rules |
|---|---|---|
| `tags` | array of strings | 0 to 8 tags, each 1 to 32 chars, lowercase `a-z0-9-_`, shown with a leading `@` |
| `priority` | 1, 2, or 3 | Already in the schema; 1 is highest. Shown as `#1`/`#2`/`#3` |
| `body_format` | `"plain"` or `"markdown"` | Default `plain`. Todos written by the bot writer use `markdown` |
| `body` | string | Raise the limit to 8000 characters for `kind: todo` when `body_format` is `markdown`. Other kinds keep 1000 |
| `waiting` | object | `{on, check_back}` stays. Optional `since` is `YYYY-MM-DD`. A todo with `waiting` set shows in the Waiting view |
| `owner` | `"user"` or `"bot"` | Default `user`. Drives the Mine and Bots views |
| `due` | string | Existing formats. A time part means a due time; date-only means end of day |

Per feed file, optional top-level `tag_colors`: a map of tag to one of a fixed palette name (`red`, `orange`, `yellow`, `green`, `teal`, `blue`, `purple`, `pink`, `gray`). Tags without an entry get a stable color from a hash of the tag name, so the same tag is always the same color on every machine. Palette names, not hex codes, so the window and popup can pick shades that read well in light and dark themes.

The secret guard in PROTOCOL.md also scans `tags`. A long Markdown body is scanned the same way as a plain one.

## 4. Chips and colors

| Chip | Color |
|---|---|
| Due, overdue | red |
| Due today | amber |
| Due within 3 days | yellow |
| Due later | neutral |
| Created | green, muted |
| Tag | its palette color |
| Priority `#1` | red; `#2` amber; `#3` neutral |

Dates show as `Due Tue 10/20 10:00` or `Due 10/20`, in the desktop's local time zone. Overdue items sort to the top of every view.

## 5. Top-bar popup changes

- Each todo row: priority, title (one line, ellipsized), then a chip row with due and up to 3 tags (`+2` if more).
- Clicking a row's title opens the TetherBot window on that item. Done stays a button on the row.
- A search entry at the top of the todos section filters rows as you type (title, body, tags).
- Show at most 8 todos; then "Open TetherBot to see all N".
- "Open TetherBot" button in the footer.

## 6. TetherBot window

Layout: an adaptive split view. List on the left, detail on the right. On a narrow window it collapses to list, then detail with a back button.

List pane:
- Search entry at the top. Keyword search over title, body, and tags, case-insensitive, all words must match. `@tag` in the search box filters by that tag; `due:today`, `due:overdue`, and `p:1` are supported shortcuts.
- Quick views as a tab row, matching what the owner already uses: All, Mine, Bots, Waiting, Today.
  - Mine: `owner` is user. Bots: `owner` is bot. Waiting: `waiting` is set. Today: due today or overdue.
- Tag filter: a row of tag chips (all tags in open items, with counts). Click to toggle; multiple tags mean all must match. A "clear" chip resets.
- Sort menu: due (default), priority, created, updated.
- Each row: checkbox (Done), priority, title, chip row. Done rows leave the list on tap, same as the popup.
- A "Show done" toggle reveals completed todos inside the history window from Settings. The default is on, for 1 year. The How many row in Settings says that 1 month = 30 days and 1 year = 365 days. When history is off, the toggle shows no done todos. Dropped items stay hidden. The rows are read-only. An older done todo is left out of the view. The desktop does not rewrite the bot's feed file.

Detail pane:
- Title, then the chip row (due, created, priority, tags, waiting-on).
- Body rendered as Markdown: headings, bold, italic, inline code, code blocks, bullet and numbered lists, task-list checkboxes (display only), block quotes, and links. Links open in the default browser after a click, never automatically. Images and raw HTML are not rendered.
- Buttons: Done, Copy Todo, and "Ask the bot about this", which uses the existing `SendToBot` path to send a note with the item key so the owner can say "change the due date" or "add a tag" in chat. Copy icons beside the title and the body copy only that part. The note includes the owning bot id.
- Source line: which bot, which routine, last updated.

Rendering: a small built-in Markdown subset renderer into a GtkTextView (or GtkLabel markup) with no JavaScript and no web engine. No new runtime dependency.

Keyboard: `Ctrl+F` focuses search, `Up`/`Down` move, `Enter` opens, `Ctrl+Enter` marks done, `Esc` clears search.

## 7. D-Bus additions

- `OpenWindow(s item_key)`: bridge launches or raises the window, selecting the item if the key is not empty.
- `GetItems` gains filter fields: `tags`, `query`, `view`, `include_done_days`, `include_done_seconds`. Filtering happens in the bridge so the popup and window agree. `include_done_seconds` is the history window. When both done keys are set, seconds wins. Only a completed todo is added.
- `GetTags() -> s` (JSON): tags in open items with counts and resolved palette colors.
- Existing `PerformAction` stays the only way to send Done.

## 8. Bot writer changes (`tools/feed_write.py`)

- `add-todo` gains `--tag` (repeatable), `--priority 1|2|3`, `--owner user|bot`, `--waiting-on TEXT`, `--body-file PATH` (Markdown from a file), and `--markdown` (default on for todos).
- New `edit --key ... [--title] [--body|--body-file] [--due|--clear-due] [--add-tag|--remove-tag] [--priority] [--waiting-on|--clear-waiting]`. This is how "have the bot edit it" works.
- New `tag-color --tag NAME --color PALETTE`.
- Same idempotency, conflict retry, secret guard, and never touching `desktop/`.

## 9. Cutover from the older app (not part of this step)

After the checklist in section 1 passes on the desktop, a separate step moves open items over (mapping its tags, due dates, priorities, and Markdown bodies), switches the daily summary run to the feed, and retires the older sync. Until then, only test todos go to TetherBot.

## 10. Manual checks to add

M17 is already the uninstall check, so these are M18–M24 in [MANUAL-CHECKS.md](MANUAL-CHECKS.md).

- M18. A todo with 3 tags, a due time, priority 1, and a Markdown body shows correct chips in the popup and window.
- M19. Search for a word only in a body finds the item in both popup and window.
- M20. Tag filter with two tags shows only items with both. Quick views match their rules.
- M21. Opening an item renders headings, lists, code, and a link; clicking the link opens the browser.
- M22. Done from the detail pane hides the item in both popup and window and reaches the bot.
- M23. A feed with no new fields still renders exactly as before.
- M24. The window starts from the popup button, holds no secrets, and makes no network requests.

## 11. Decisions

1. The window ships with a .desktop file and appears in the app grid as a normal app, so it opens without the top bar.
2. Done has no confirmation prompt. The window and popup show a 5-second Undo. While that Done action is still in the local queue (the webhook sender batches and paces, so nothing has been sent), Undo drops it with `DropQueued` and unhides the item. If it has already gone out, Undo sends `reopen` and brings the item back.
3. The existing local-only snooze stays in the popup.

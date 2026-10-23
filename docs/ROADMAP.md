# Roadmap

TetherBot is pre-alpha. Check items off as they land. Design detail is in [SPEC.md](SPEC.md). Anything marked **TBD, verify** there is an open checkbox under Open checks. Do not treat those as decided. The Resolved list is decided.

## v0.1 — one desktop

- [x] Config loader and logging with redaction
- [x] Bridge daemon process and GLib main loop
- [x] D-Bus service exporting `data/io.github.grokkinggrok.TetherBot1.xml` on the session bus
- [x] Item store, diff, and notify policy
- [x] On-disk action queue with `fsync`, restart resume, coalescing, and pacing
- [x] Secret-service read and write (`io.github.grokkinggrok.TetherBot.Secret`), no plain-file fallback
- [x] `tetherbotctl` for status, enable, secret set, and webhook test
- [x] `webhook-sender`: POST, bearer header, retry table in SPEC section 7.2, re-paste flow
- [x] `github-poller`: change check, schema gate, owned-path writes, fail closed on rebase conflicts
- [x] Minimal extension: indicator counts, popup (bots, todos, asks), notifications with actions
- [x] Extension talks only D-Bus; proxy and handlers dropped in `disable()`
- [x] Installer places the app, launchers, unit, and D-Bus activation. `ExecStart` is `%h/.local/bin/tetherbot`
- [x] `git-credential-tetherbot` for `https-token` (token stays in libsecret). `ssh-deploy-key` stays deferred
- [x] `template-repo/` for the private data repository
- [x] `docs/MANUAL-CHECKS.md` for M1–M8 and M10–M14
- [x] Manual checks M1–M8 and M10–M14 passed on Fedora 44 / GNOME Shell 50. M9 is not in this set.
- [x] Concrete legacy inbox format stays out of this public repo. The in-tree `legacy-todo` sink stays generic.
- [ ] Manual checks M15 and M16 only if a sink outside this repo is enabled

## v0.1.x — bot-written todos (next)

- [x] Bot write access to the private data repo, using the decided fine-grained token (see Resolved). The writer is `tools/feed_write.py` (#18). The token stays in an environment variable on the bot (default `TETHERBOT_FEED_TOKEN`), never in this repo. An expired token exits with a one-line error.
- [x] Crash-proof stopwatch and the robot top-bar icon, [STOPWATCH.md](STOPWATCH.md). One timer, stored by the bridge in `timer.json`. This is the last item before the single-tracker cutover.
- [x] TetherBot is the single todo tracker. An older local todo sync is retired after cutover, not run in parallel.
- [x] Remote capture. The user messages their bot from a phone while away. The bot writes a `kind: todo` item with `tools/feed_write.py add-todo`. The desktop shows it on the next poll or at boot. Done in the popup reports back over the webhook, and the bridge records the item closed (the existing flow).
- [x] A bot's daily summary run can post that day's asks and todos with `tools/feed_write.py` (`add-ask`, `add-todo`, and `status`). The desktop bot row shows `status.summary` when that block is set, and otherwise counts the open items.
- [x] `feed/<bot>.json` for more than one bot. The writer accepts `--bot` and edits only that bot's file. `"bot"` stays the string id, so an existing `feed/primary.json` needs no migration. A second bot is another file, for example `feed/notes.json`.
- [x] Bot display names. The popup, window, filters, and notifications show each tethered bot's chosen name instead of the config slug, such as `Primary`. The bot publishes that name as `display_name` in `feed/<bot>.json`, set by `tools/feed_write.py` (a `--name` option on `status`). A `bot` object `{"id", "display_name"}` is also accepted. The desktop reads it. An optional per-bot `display_name` in `config.toml` wins when it is set. With no published name and no override, the label is the slug, title-cased. A bot added later shows its name with no desktop change. The slug stays the stable id for the webhook slot, file names, and action routing. Only the label changes.
- [x] Popup section order. The toolbar popup order is Timer, Todos, Asks, Bots, then Open TetherBot, the status line, Sync now, and Settings.
- [x] Compact Bots section for more than one tethered bot. When there is more than one bot, the popup's Bots section collapses to one summary line, for example `3 bots · all ok`. An individual bot row appears only when that bot is stale, broken, needs attention, or has a pending ask, and the summary names the bot (or counts them). Needs attention is amber. A bot in state `error`, or a bridge failure, keeps that line red. A healthy setup is one line however many bots there are. The full per-bot list (display name, last seen, next run, open todo count) lives in the Bots tab of the TetherBot window, with a name filter. Clicking the summary opens it. Bot names also act as filters on todos, the way tag chips do. With a single bot, the line reads like today's row.
- [ ] More than one desktop can read the same feed, for example a second, rarely used machine. macOS is not GNOME, so a non-GNOME client is out of scope for now. On a second machine the bot side is the entry point for adding todos.
- [ ] Proposed, not urgent: each desktop writes only `desktop/<machine-id>.json` (see Open checks). Matters once a second GNOME desktop exists.
- [ ] Optional later: an always-on local device, for example a single-board computer, as a physical attention indicator or a hub. Not required, because the private repo is already the always-on middle.
- [ ] The feed writer's secret filter (`looks_like_secret` in tools/feed_write.py and the matching guard in the bridge) lets ordinary http(s) URLs through. Right now a GitHub link such as the MANUAL-CHECKS.md URL trips the 40-or-more-character letter-run rule, so bots have to pad links with `./` segments. Strip or exempt URLs before the check, and keep real tokens blocked.
- [x] Rich todos, [RICH-TODOS.md](RICH-TODOS.md) (#19–#21). Bots still create and edit item text. The desktop reads, filters, searches, opens, and checks off.
- [x] Optional feed fields: `tags`, `body_format`, Markdown bodies up to 8000 characters on todos, `owner` of `user` or `bot`, `waiting.since`, and feed `tag_colors`
- [x] Bridge search and filters (`@tag`, `due:today`, `due:overdue`, `p:1`), quick views, `GetTags`, and sort. Popup and window share that result
- [x] Undo drops a queued Done before it is sent, and sends `reopen` only after it has gone out
- [x] `tools/feed_write.py` gains tags, priority, owner, waiting-on, body-file, edit, and tag-color
- [x] TetherBot window (GTK4 and libadwaita): list, detail Markdown, `.desktop` file, and `OpenWindow`
- [x] Popup: chips, search, at most 8 todos, Open TetherBot, and a 5-second Undo
- [x] Manual checks M37–M41 passed on the desktop: the minute top-bar format, edit start, the close button and a single titlebar, attach via Add to a todo and Attach timer, Undo after Stop including a paused timer, and a stopped unassigned timer that survives with Dismiss.
- [ ] Manual checks M18–M36 and M42 for the rich todo view, login start, window open, and the remaining stopwatch checks. Login start and non-blocking window open are on main (#22, #23). The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). M18–M36 and M42 have not been run on the desktop yet.
- [x] Manual checks M43–M46 passed on the desktop: a second feed file, display names, the compact Bots section, popup order Timer then Todos then Asks then Bots, and the window Bots tab (summary click, name filter, and the list of bots).
- [x] Manual check M47 passed on the desktop: the timer still behaves after the new popup.
- [x] Manual checks M48–M54 passed on the desktop: a bot without a webhook slot, Sync now, the timer chip, the toolbar with no counts and the todo dot, the readable summary, the window bot status dot, and local-time dates.
- [x] Manual checks M55–M57 passed on the desktop: the timer chip on the left, a top bar that hugs the timer text, and a window that updates bot names while it stays open.
- [x] Manual checks M58 and M62 passed on the desktop: the panel icon matches the shell's icon size, and `primary` stays the first bot.
- [x] Manual checks M63 and M64 passed on the desktop: several bots can share one webhook slot, and a missing secret stays on that bot.
- [x] Manual checks M65–M68 passed on the desktop: the face takes the shell accent, both eyes stay visible, Done sends when the shared bar ends, and one menu sends one batch.
- [ ] Manual checks M69–M73 for the settings screen: key handoff, poll interval, undo length, notifications per bot, and hidden bots. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet.
- [x] Manual checks M74–M77 passed on the desktop: reset to defaults, the corner badge with blue for asks confirmed, one notification per new item, and popup Done sending when the undo bar ends.
- [x] Manual checks M78 and M79 passed on the desktop: editing a todo's tracked total and deleting a time record, and an amber bots summary for needs attention with red kept for an error or a bridge failure.
- [x] Manual checks M80 and M81 passed on the desktop: Stop timer on the open todo, and copy icons for the title and the body plus Copy Todo.
- [x] Manual check M82 passed on the desktop: completed todos stay in Show done for the history window, history filtering updates live, and Reset to defaults leaves that setting alone.
- [ ] Manual checks M83–M95: Enter in the edit-start time field, Done while the pointer stays on the row, the How many unit note, a window that opens at the list's height without clipping the last row, the upper-right of the work area, Done with note, the disabled empty note, the wider window still fitting at the upper right, fixed detail buttons, the centered undo bar, Done while the receiver is unreachable, and detail buttons that stay one line tall and fully on screen. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet.
- [ ] Manual checks M96–M104: even gaps in the detail button row, and clipboard history phase 1 (capture, the panel menu copies an entry back, the window search and delete, a password-manager copy is skipped, an excluded app is skipped, Clear, the toggle, and nothing reaches the feed). The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. M96 reopens the window. M97–M104 need a log out so the extension and the schema load.
- [ ] Manual checks M105–M108: a Chrome password copy is not kept, ordinary text is not treated as a password, Hide for 30 seconds masks a password-like copy and then deletes it, and `tetherbotctl clipboard-debug` prints MIME types and the reason without the text. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. They need a log out so the extension and the schema load.
- [ ] Manual checks M109–M113: pin survives the cap and Clear, tags and the tag filter, edit keeps the pin and the tags, preview keeps line breaks, and Search the web uses the desktop engine only when pressed. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. They need a log out so the extension and the bridge load.
- [ ] Manual checks M114–M116: the tag filter does not freeze the window, Search the web follows Chrome's engine or the Settings fallback, and a hidden password can be pinned but not tagged. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. They need a log out so the extension, the schema, and the window load.
- [ ] Manual check M117: Settings opens without an error, and the Clipboard search fallback row shows its hint. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). Close Settings and open it again after this version is installed.
- [ ] Manual checks M118 and M119: the Clipboard page and the panel menu use one icon row per entry, the text stays one line, and a pin uses the accent color. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. M118 reopens the window. M119 needs a log out so the menu loads.
- [ ] Manual checks M120–M126: clipboard images. A copied screenshot is kept, the row stays one line, Preview and Copy restore the original type, pin and tag work, delete and clear remove the files, and an excluded app or Remember copied images off leaves a new image out. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. They need a log out so the extension and the schema load.
- [ ] Manual checks M127–M130: clipboard menu icons stay fully visible, the todo-list Start timer icon stays fully visible, Remember copied images matches Remember copied text, and the tag icon is a monochrome symbol. The steps are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md). They have not been run on the desktop yet. They need a log out so the extension, the schema, and the window load.

## v0.2 — early adopters

- [x] `template-repo/` for the private data repository
- [x] `https-token` mode and `git-credential-tetherbot`
- [ ] `desktop/outbox` for repo-only actions
- [x] Polish `scripts/install.sh` and `scripts/uninstall.sh` against a real daemon
- [ ] Review the two prompts in `docs/prompts/` against the running app
- [x] `docs/privacy.md` (session-bus trust boundary, what leaves the machine). Draft.
- [x] GTK4 key dialog owned by the bridge process
- [x] Extension prefs (gsettings, UI only) and a "Set up keys..." button
- [ ] COPR RPM — interest is **TBD, verify**
- [ ] Feedback from a handful of users
- [ ] All manual checks M1–M17

## v1.0 — extensions.gnome.org

- [ ] No network and no secrets in the extension; clean `disable()`; shell does not spawn processes
- [ ] `shell-version: ["50"]` on the published listing (UUID `tetherbot@grokkinggrok.github.io` is decided)
- [ ] gettext translations
- [ ] Keyboard and screen-reader access
- [ ] Quick Settings tile
- [ ] `official` adapter, if an official API exists
- [ ] Name, icon, and wording checked against Grok Bot brand rules. The listing stays labelled unofficial, not affiliated with xAI.
- [ ] Deprecation policy for `io.github.grokkinggrok.TetherBot1` and schema `tetherbot/1`

## Open checks (TBD, verify)

- [ ] Webhook rate-cap status and body (reported as HTTP 400), and the wording that means the payload itself is invalid
- [ ] Whether HTTP 401 and 403 are the bad-key statuses
- [ ] Maximum webhook body size
- [ ] Whether the webhook response includes a run id
- [ ] Required `Content-Type` (plan: send `application/json`)
- [ ] Rate-limit numbers for routine webhooks
- [ ] Key rotation without recreating the routine
- [ ] Deep link to a specific bot chat, and the Grok Bot desktop entry id. Until that exists, the desktop does not show an Open chat button and a bot row does not claim to open that chat.
- [ ] Proposed, not urgent (only once a second GNOME desktop exists): each desktop writes only `desktop/<machine-id>.json`. `machine-id` is a stable random id generated at install, not the hostname. No two machines write the same file, so pushes cannot conflict. A tap on one desktop resolves the item; every desktop reads all `desktop/*.json` files and hides an item that any desktop has resolved. Snooze stays local to one machine. Migration: the current single-desktop `desktop/state.json` is read as a legacy file and renamed on first run.
- [ ] Whether Grok Bot ships outbound webhooks, status events, or a local hook that can replace `github-poller`
- [ ] Decide whether a local todo consumer should call `GetItems` or keep parsing its file
- [ ] Decide whether popup Done on a legacy todo writes the local file or only sends a webhook (proposed: write the file when that sink is the source of truth)
- [ ] Git-over-HTTPS rate limits for `ls-remote` every 2 minutes; fall back to REST with ETag if throttled
- [ ] GNOME 50 `MessageTray.Notification` action API
- [ ] Nested shell devkit command and package on Fedora 44 (`dbus-run-session gnome-shell --devkit` is the candidate)
- [ ] Which `systemd --user` sandbox options work on Fedora 44 without breaking libsecret or git, including `ProtectSystem=strict` with `ReadWritePaths=`
- [ ] Whether a COPR package is worth building for v0.2

## Later

- [ ] Start the stopwatch when the user logs in. The bridge already starts with the graphical session. Starting the timer itself on login is not built.
- [ ] Money and watch section. Todo filters cover the need for now. A visual money overview is a possible future teaser, not part of v0.2.
- [ ] Webhook-only mode copy in the popup. Webhook-only mode is not being pursued.
- [ ] Lint the GNOME Shell extension JavaScript. Python is already linted with ruff in CI and passes. The `extension/*.js` files have no linter. Add ESLint (GJS/GNOME Shell globals, ES modules) to the Makefile and CI, then fix what it reports.

## Clipboard history

Phase 1 is built, and copied images are kept too. Text and images stay on this machine. A clipboard entry is never written to the feed repository, to `desktop/*`, or into a log. It is not sent to a bot unless a later phase's send button is pressed. This is the stand-in for a separate clipboard-history extension. The toolbar icon shows no count. The timer text stays the only number in the toolbar. Direct paste into the active window is out of the plan. The reason is [CLIPBOARD.md](CLIPBOARD.md).

The extension reads the clipboard for this history. [privacy.md](privacy.md) says what stays on the machine. The text and the image files stay on this machine except for the phase 4 buttons, which are not built.

- [x] Phase 1. Capture plain text into local state, not the feed clone. The file is mode 0600. A setting chooses how many entries to keep (default 50, from 1 to 500) and can turn capture off. Clear removes unpinned entries. Skip an entry the clipboard marks sensitive (`x-kde-passwordManagerHint`, a concealed, sensitive, or confidential type) and a copy taken while the focused window's class is on the exclude list. The default exclude list is common password managers. Chrome on Linux does not set one of those types, so a password-like line (one line, no spaces, 8 to 128 characters, three or more character classes, not a URL, path, number, email, UUID, or simple file name) is skipped too. Settings can instead keep that line hidden for 30 seconds. `tetherbotctl clipboard-debug` prints the last offer's MIME types and the reason, not the text. Its own toolbar icon opens a menu of recent entries. Choosing one copies it back onto the clipboard. The TetherBot window has a Clipboard page with search, Copy, and Delete.
- [x] Phase 2. Tag, Pin, Edit, and Preview. Pin and unpin from the panel menu and the Clipboard page. Pinned entries sort first, stay past the item limit, and stay when Clear runs. Delete still removes a pinned entry. A hidden password still expires after 30 seconds. Each entry can have up to eight tags, each with a palette color. The Clipboard page filters by tag, and search matches tag names. Edit replaces the text and keeps the pin and the tags. A hidden password cannot be edited. A click opens a read-only view of the full text with line breaks kept. The list shows a shortened single line. Copying an entry back onto the clipboard is already part of phase 1. That copy does not type into another window.
- [x] Phase 3. Web search. Search the web is on the Clipboard page. It opens the default browser with that browser's saved search template, including a Chromium `{google:baseURL}` template and Web Data. When that cannot be read, the button uses the search fallback shown in Settings. The default is DuckDuckGo, and the address can be changed. A hidden password cannot be searched. Nothing leaves the machine unless that button is pressed. The extension does not open a browser.
- [ ] Phase 4. Three send-to-bot buttons, each a webhook note answered in the bot chat: "make a new todo", "make a new todo and search my bot and TetherBot data for context", and "tell me more". The text leaves the machine only when one of those is pressed. The send goes through the bridge. The extension does not open a socket.
- [x] Images (Batch J). Copied images (image/png and other image/* types) are kept on this machine under the state dir, each file mode 0600, up to 10 MiB each and 20 unpinned images, counting toward the item limit. Thumbnails in the panel menu and Clipboard page; Preview shows the full image; Copy restores the original type; Pin, Tag, Delete, and Clear work; Edit and Search the web are dimmed. A setting turns image capture off. Images never reach the feed, logs, or webhooks.

## Resolved

- [x] Attention on the symbolic face is one small filled dot in the bottom-right corner. The face follows the theme accent and stays fully visible. An open todo is red. An ask, or a bot that needs attention, is blue, and blue wins when both apply. There is no ring. The dot scales with the shell's panel icon and stays inside the icon box.
- [x] Bus name and interface `io.github.grokkinggrok.TetherBot1`, object path `/io/github/grokkinggrok/TetherBot1`. Schema string stays `tetherbot/1`. Libsecret schema `io.github.grokkinggrok.TetherBot.Secret`. Do not change the bus name after release.
- [x] Extension UUID `tetherbot@grokkinggrok.github.io`. The README and the extension metadata description stay labelled unofficial, not affiliated with xAI.
- [x] Concrete legacy inbox format stays out of this public repo. The `legacy-todo` sink stays generic.
- [x] Bot write credential: a fine-grained personal access token scoped to the private data repo only. Permissions are Contents read and write, plus Metadata read (GitHub requires it), and nothing else. Held on the bot side as a bot secret, never on the desktop or in this repository. The bot writes over HTTPS and the REST contents API, which an SSH-only deploy key cannot do, and this matches the desktop's `https-token` mode. Fine-grained tokens expire (maximum 1 year). The bot owner sets a renewal reminder before expiry. An expired token must fail visibly: the bot reports it, and posting does not stop in silence.

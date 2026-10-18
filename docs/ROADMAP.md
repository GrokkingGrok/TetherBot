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

- [ ] Bot write access to the private data repo. A token scoped to that repo only, held on the bot side, never on the desktop and never in this repository. This is the decision for "how a bot should hold write access."
- [ ] TetherBot is the single todo tracker. An older local todo sync is retired after cutover, not run in parallel.
- [ ] Remote capture. The user messages their bot from a phone while away. The bot writes a `kind: todo` item to `feed/<bot>.json`. The desktop shows it on the next poll or at boot. Done in the popup reports back over the webhook, and the bridge records the item closed (the existing flow).
- [ ] A bot's daily summary run can post that day's asks and todos to the feed.
- [ ] `feed/<bot>.json` for more than one bot
- [ ] More than one desktop can read the same feed, for example a second, rarely used machine. macOS is not GNOME, so a non-GNOME client is out of scope for now. On a second machine the bot side is the entry point for adding todos.
- [ ] Per-desktop acted and closed state in `desktop/state.json` when two desktops share one feed, so the two machines do not push conflicting state. See Open checks.
- [ ] Optional later: an always-on local device, for example a single-board computer, as a physical attention indicator or a hub. Not required, because the private repo is already the always-on middle.

## v0.2 — early adopters

- [x] `template-repo/` for the private data repository
- [x] `https-token` mode and `git-credential-tetherbot`
- [ ] `desktop/outbox` for repo-only actions
- [x] Polish `scripts/install.sh` and `scripts/uninstall.sh` against a real daemon
- [ ] Review the two prompts in `docs/prompts/` against the running app
- [ ] `docs/privacy.md` (session-bus trust boundary, what leaves the machine)
- [ ] GTK4 key dialog owned by the bridge process
- [ ] Webhook-only mode copy in the popup
- [ ] Money and watch section
- [ ] Extension prefs (gsettings, UI only) and a "Set up keys..." button
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
- [ ] Deep link to a specific bot chat, and the Grok Bot desktop entry id
- [ ] How the bot authenticates writes to the data repo: a fine-grained token or a deploy key. Either way the credential stays on the bot side, scoped to that repo only, and is never stored on the desktop or in this repository.
- [ ] Two desktops sharing one feed: how `desktop/state.json` keeps per-desktop acted and closed state without both machines pushing conflicting state
- [ ] Whether Grok Bot ships outbound webhooks, status events, or a local hook that can replace `github-poller`
- [ ] Decide whether a local todo consumer should call `GetItems` or keep parsing its file
- [ ] Decide whether popup Done on a legacy todo writes the local file or only sends a webhook (proposed: write the file when that sink is the source of truth)
- [ ] Git-over-HTTPS rate limits for `ls-remote` every 2 minutes; fall back to REST with ETag if throttled
- [ ] GNOME 50 `MessageTray.Notification` action API
- [ ] Nested shell devkit command and package on Fedora 44 (`dbus-run-session gnome-shell --devkit` is the candidate)
- [ ] Which `systemd --user` sandbox options work on Fedora 44 without breaking libsecret or git, including `ProtectSystem=strict` with `ReadWritePaths=`
- [ ] Whether a COPR package is worth building for v0.2

## Resolved

- [x] Bus name and interface `io.github.grokkinggrok.TetherBot1`, object path `/io/github/grokkinggrok/TetherBot1`. Schema string stays `tetherbot/1`. Libsecret schema `io.github.grokkinggrok.TetherBot.Secret`. Do not change the bus name after release.
- [x] Extension UUID `tetherbot@grokkinggrok.github.io`. The README and the extension metadata description stay labelled unofficial, not affiliated with xAI.
- [x] Concrete legacy inbox format stays out of this public repo. The `legacy-todo` sink stays generic.
- [x] A bot's write access to the private data repo is a credential scoped to that repo only, held on the bot side. It is never stored on the desktop or in this repository. Fine-grained token versus deploy key is still an open check.

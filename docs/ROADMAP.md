# Roadmap

TetherBot is pre-alpha. Check items off as they land. Design detail is in [SPEC.md](SPEC.md). Anything marked **TBD, verify** there is an open checkbox in the last section of this file. Do not treat those as decided.

## v0.1 — one desktop

- [ ] Bridge daemon process, GLib main loop, config loader, logging with redaction
- [ ] D-Bus service exporting `data/org.tetherbot.Bridge1.xml` on the session bus
- [ ] Item store, diff, and notify policy
- [ ] On-disk action queue with `fsync`, restart resume, coalescing, and pacing
- [ ] Secret-service read and write (`org.tetherbot.Secret`), no plain-file fallback
- [ ] `tetherbotctl` for status, enable, secret set, and webhook test
- [ ] `webhook-sender`: POST, bearer header, retry table in SPEC section 7.2, re-paste flow
- [ ] `github-poller`: change check, schema gate, owned-path writes, fail closed on rebase conflicts
- [ ] Minimal extension: indicator counts, popup (bots, todos, asks), notifications with actions
- [ ] Extension talks only D-Bus; proxy and handlers dropped in `disable()`
- [ ] Manual checks M1–M8 and M10–M14
- [ ] `legacy-todo` shadow mode, comparison command, and cutover — only if a concrete legacy format is in scope for this machine
- [ ] Manual checks M15 and M16 when that sink is enabled

## v0.2 — early adopters

- [ ] `template-repo/` for the private data repository
- [ ] `feed/<bot>.json` for more than one bot
- [ ] `https-token` mode and `git-credential-tetherbot`
- [ ] `desktop/outbox` for repo-only actions
- [ ] Polish `scripts/install.sh` and `scripts/uninstall.sh` against a real daemon
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
- [ ] `shell-version: ["50"]` and a confirmed extension UUID
- [ ] gettext translations
- [ ] Keyboard and screen-reader access
- [ ] Quick Settings tile
- [ ] `official` adapter, if an official API exists
- [ ] Name, icon, and wording checked against Grok Bot brand rules, with unofficial labelling if required
- [ ] Deprecation policy for `org.tetherbot.Bridge1` and schema `tetherbot/1`

## Open checks (TBD, verify)

- [ ] Webhook rate-cap status and body (reported as HTTP 400), and the wording that means the payload itself is invalid
- [ ] Whether HTTP 401 and 403 are the bad-key statuses
- [ ] Maximum webhook body size
- [ ] Whether the webhook response includes a run id
- [ ] Required `Content-Type` (plan: send `application/json`)
- [ ] Rate-limit numbers for routine webhooks
- [ ] Key rotation without recreating the routine
- [ ] Deep link to a specific bot chat, and the Grok Bot desktop entry id
- [ ] How a bot should hold write access to the private data repo
- [ ] Whether Grok Bot ships outbound webhooks, status events, or a local hook that can replace `github-poller`
- [ ] Confirm the bus name `org.tetherbot.Bridge1` before v0.2, then freeze it
- [ ] Confirm the extension UUID `tetherbot@example.invalid` and whether the listing must say unofficial
- [ ] Decide whether a local todo consumer should call `GetItems` or keep parsing its file
- [ ] Decide whether popup Done on a legacy todo writes the local file or only sends a webhook (proposed: write the file when that sink is the source of truth)
- [ ] Git-over-HTTPS rate limits for `ls-remote` every 2 minutes; fall back to REST with ETag if throttled
- [ ] GNOME 50 `MessageTray.Notification` action API
- [ ] Nested shell devkit command and package on Fedora 44 (`dbus-run-session gnome-shell --devkit` is the candidate)
- [ ] Which `systemd --user` sandbox options work on Fedora 44 without breaking libsecret or git, including `ProtectSystem=strict` with `ReadWritePaths=`
- [ ] Whether a COPR package is worth building for v0.2

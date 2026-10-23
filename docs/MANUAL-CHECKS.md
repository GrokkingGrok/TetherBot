# Manual checks (v0.1)

Run these on one Fedora 44 desktop with GNOME Shell 50 on Wayland, after you can log in as a normal user. The project is unofficial and not affiliated with xAI.

**Out of scope here:** M9 (webhook-only popup copy), M15 and M16 (a legacy todo sink outside this repository), and M17 (the full uninstall acceptance check). Uninstall is still documented in [SETUP.md](SETUP.md) and is the reset for M1. M18–M24 are the rich-todo checks later in this file. M25 checks that a new login starts the bridge. M26 checks that a todo click opens the window quickly. M27–M42 check the stopwatch. M43–M47 check more than one bot, display names, the compact Bots section, and the popup order. M48–M54 check an optional webhook slot, Sync now, the timer chip, toolbar colors, summary contrast, the bot-row dot and summary, and local dates. M55–M57 check the timer chip on the left, the top-bar width, and a window that updates while it stays open. M47 and M55–M68 passed on the desktop. M58 and M62 are the panel icon size and `primary` staying first. M59–M61 are replaced by M65–M68: a face in the shell's status-icon color, eyes that stay visible, Done sending when the shared bar ends, and one batch per menu. M74 passed on the desktop: reset to defaults restores the feed check and the undo timer. M75 passed on the desktop: the corner badge is in place, and blue for asks was confirmed. M76 passed on the desktop: one new item raises one notification, including after a bridge restart. M77 passed on the desktop: popup Done sends when the undo bar ends, and closing the menu early does not send it. M63 and M64 are a shared webhook slot and a missing secret on one bot. M69–M73 check the settings screen. M78 passed on the desktop: editing a todo's tracked total and deleting a time record. M79 passed on the desktop: the bots summary is amber for needs attention and red for an error or a bridge failure. M80 passed on the desktop: Stop timer on the open todo. M81 passed on the desktop: the title copy icon, the body copy icon, and Copy Todo. M82 passed on the desktop: completed todos stay in Show done for the history window, and Reset to defaults leaves that setting alone. M83–M119 are still open. M96 is even detail-button spacing. M97–M104 are clipboard history phase 1. M105–M108 check a Chrome password copy, the password-like rule, hiding one for 30 seconds, and the local debug command. M109–M113 check pin, tags, edit, preview, and Search the web. M114–M116 check the tag filter, Chrome's search engine, and tags on a hidden password. M117 checks that Settings opens and the search fallback hint is visible. M118 and M119 check the single-line clipboard icon row on the page and in the menu. Do not treat M9, M15, M16, or M17 as part of the v0.1 runbook.

Examples use the bot id `primary`. Yours can be any lowercase id of letters, digits, and hyphens. Use the same id in the bot's feed file, in `config.toml`, and in the commands below.

Nothing in these steps belongs in a chat, in `config.toml`, or in this repository: not the webhook URL, not the webhook key, and not the GitHub token. Paste them only in the bridge key dialog opened from Settings, or at the hidden prompt from `tetherbotctl secret set`. A stored key is never shown.

## Suggested order

M1, M2, then the extension install in M14 (log out and back in once), then M3. Do M10 before M4 if the popup has no ask yet. Then M4, M10a, M5, M11, M6, M7, M8, M12, M13. After a rich todo is in the feed, M18 through M24. M25 is the next login after the unit is installed. M26 is a todo click after that. M27 through M42 need a running timer. M43 through M47 need this version installed and a log out, then a second feed file. M48 through M54 need that same login. M47 and M55 through M68 passed on the desktop. M74 through M77 passed on the desktop. M69 through M73 need the settings install and a log out, so the prefs window and the schema load. M78 through M82 passed on the desktop. M83 needs a running or paused timer. M84 needs an open todo. M85 needs the settings screen. M86 through M95 need the TetherBot window. M88 and M91 use the extension that places the window. M93 also uses the toolbar menu's undo bar, so that needs a log out if the extension has not reloaded since this version was installed. M89, M90, M92, M94, and M95 do not need a log out. Reopen the window after the old window process exits. M96 reopens the window after the old window process exits. M97 through M116 need a log out and back in, so the clipboard icon, the settings schema, and the bridge load. M109 through M116 also need the window process started after that login. M117 reopens Settings after this version is installed. M118 reopens the window after the old window process exits. M119 needs a log out and back in, so the clipboard menu loads.

You can stop after any check. Later checks say what they need.

## Once, before the checks

1. Install Grok Bot and sign in. Pick the bot that should receive desktop actions.
2. Paste [prompts/bot-setup.md](prompts/bot-setup.md) into that bot's chat. It asks for a routine named "Desktop actions" with a webhook trigger. Do not paste a key into the chat.
3. Open the routine on the desktop: bot name, Details, Routines, the routine. In **Webhook**, find **POST to** and **key**. Leave that window open. You will paste them only when a check says to run `tetherbotctl secret set`.

From a clone of this repository:

```bash
scripts/install.sh
```

That writes the app, three launchers, the user unit, and the D-Bus activation file. It does not start the bridge. If `~/.local/bin` is not on your `PATH`, open a new terminal or add it for this session:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Dependency warnings from the installer are not fatal. Python 3.13+, PyGObject, the Secret-1 typelib, and git should be installed before you rely on a check that needs them.

## M1. Install on a clean user, status unconfigured

**Preconditions.** A user account that has not installed TetherBot, or one you have cleaned with the reset below. The login keyring is unlocked, which is normal after you type your password at the graphical login.

**Commands.**

```bash
scripts/install.sh
systemctl --user enable --now tetherbot
tetherbotctl status
```

`scripts/install.sh --enable` does the same enable and start in one step.

**Look for.**

- `tetherbotctl status` prints `unconfigured`, then `reason: no adapter is enabled` (or `config.toml is missing` if you deleted the example config), then `running: yes`.
- `systemctl --user is-active tetherbot` prints `active`.
- No window asks you for a token or a webhook key.

**Reset.** Leave this install in place for the next checks. To remove it later:

```bash
scripts/uninstall.sh --purge
```

Confirm the prompt. Keyring items are kept. Add `--yes` only when there is no terminal.

## M2. Introspection matches, and D-Bus activation starts the unit

**Preconditions.** M1. The bridge may already be running.

**Commands.**

```bash
systemctl --user stop tetherbot
systemctl --user is-active tetherbot || true
gdbus introspect --session \
  --dest io.github.grokkinggrok.TetherBot1 \
  --object-path /io/github/grokkinggrok/TetherBot1
systemctl --user is-active tetherbot
```

**Look for.**

- Before the `gdbus` command, the unit is `inactive` or `failed`.
- The introspect listing includes the interface `io.github.grokkinggrok.TetherBot1` and methods such as `GetItems`, `PerformAction`, and `GetQueue`. That is the same interface as `data/io.github.grokkinggrok.TetherBot1.xml`.
- After the `gdbus` command, `is-active` prints `active`. Calling the name started `tetherbot.service`. You did not have to start it yourself.
- If the name is not found, log out and back in once so the session bus sees `~/.local/share/dbus-1/services/io.github.grokkinggrok.TetherBot1.service`, then repeat the commands.

**Reset.**

```bash
systemctl --user start tetherbot
```

Leave it running.

## M3. Webhook test returns 200

**Preconditions.** The "Desktop actions" routine exists. You can see **POST to** and **key** in its Webhook section. M2's bridge is running.

**Commands.** Edit `~/.config/tetherbot/config.toml` so the bot, the slot, and the webhook sender exist. `mode = "webhook-only"` does not enable an adapter by itself. With the sender left disabled, status stays `unconfigured` (`no adapter is enabled`) even after a test POST returns 200. The test command below posts from `tetherbotctl`, and later clicks post from the bridge, so the sender has to be enabled too. Example, with your bot id in place of `primary`:

```toml
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[adapters.webhook-sender]
enabled = true

[bots.primary]
webhook_slot = "primary-actions"
```

Restart so the bridge reads that file:

```bash
systemctl --user restart tetherbot
```

`tetherbotctl enable webhook` is the same switch if the file already has the bot and the slot.

Store the URL and the key. The prompts do not echo. Paste **POST to** at the first prompt and **key** at the second. Paste them nowhere else.

```bash
tetherbotctl secret set primary-actions
```

The command prints `stored primary-actions` and nothing else.

This next command spends one bot run. Run it only when you mean to.

```bash
tetherbotctl webhook test primary
```

**Look for.**

- The terminal prints `200` and no URL and no key.
- In that bot's chat, a reply that says `Desktop bridge connected`. The ping body may include `sent_at` and `client`. The bot treats that as a ping.
- `tetherbotctl status` is not `unconfigured`. With only the webhook sender enabled it is `ok` and the reason line is empty.
- `journalctl --user -u tetherbot -n 50 --no-pager` does not contain the key or the URL. The test POST is made by `tetherbotctl`, so the journal may not have a `webhook post` line for it.

Write down the HTTP status. The exact success body is still an open question (**TBD, verify** in [ROADMAP.md](ROADMAP.md)). A status other than 200 means no run started. Do not paste the response body into a chat.

**Reset.** Nothing to delete. The secret stays in the keyring for later checks.

## M4. Approve an ask, one accepted result

**Preconditions.** M3's webhook secret is stored. M14's extension is enabled (log out and back in first). The popup shows an open ask. That ask comes from `feed/<bot>.json` after M10, or from the local rehearsal repo below.

**Local rehearsal, if you have not done M10.** This does not contact GitHub. The bridge pushes `desktop/state.json`. Point it at a bare repo. A normal checkout rejects that push.

```bash
rm -rf "$HOME/tetherbot-rehearsal" "$HOME/tetherbot-rehearsal.git"
mkdir -p "$HOME/tetherbot-rehearsal"
cp -a template-repo/. "$HOME/tetherbot-rehearsal/"
git -C "$HOME/tetherbot-rehearsal" init -b main
git -C "$HOME/tetherbot-rehearsal" add .
git -C "$HOME/tetherbot-rehearsal" -c user.name=TetherBot -c user.email=noreply@localhost commit -m "Example feed"
git init --bare -b main "$HOME/tetherbot-rehearsal.git"
git -C "$HOME/tetherbot-rehearsal" remote add origin "$HOME/tetherbot-rehearsal.git"
git -C "$HOME/tetherbot-rehearsal" push -u origin main
```

Edit the feed in `$HOME/tetherbot-rehearsal` and push to the bare repo. The bridge's remote is the bare repo, not the checkout.

In `~/.config/tetherbot/config.toml`, set `remote` to `file://` plus the absolute path of the bare repo:

```bash
git -C "$HOME/tetherbot-rehearsal.git" rev-parse --absolute-git-dir
```

```toml
[bridge]
mode = "full"

[adapters.github-poller]
enabled = true
remote = "file:///ABSOLUTE/PATH/tetherbot-rehearsal.git"
branch = "main"
poll_seconds = 60
```

No token in the URL. Leave `[adapters.webhook-sender] enabled = true` from M3.

```bash
tetherbotctl enable webhook
tetherbotctl enable repo
systemctl --user restart tetherbot
```

Wait one poll (about a minute, or less if this is the first poll). Open the TetherBot menu. The sample ask should be listed.

**Commands.** Click **Approve** on that ask. Wait about 20 seconds. The queue holds clicks for 20 seconds so several clicks can leave as one run.

Watch the bus while you wait, in a second terminal:

```bash
gdbus monitor --session --dest io.github.grokkinggrok.TetherBot1
```

**Look for.**

- One `ActionResult` whose result is `accepted`.
- The ask leaves the popup and the badge as soon as you tap Approve. While it waits to send, the footer still counts it in the queue.
- A `PropertiesChanged` signal whose `QueueLength` is 0. The extension reads that signal for the queued count.
- The bot's chat shows the approval. The routine's instruction says to deliver the result there. The POST may include the item `title` and `kind`.
- `tetherbotctl status` shows `queue: 0` after the send. `queue:` counts pending actions only.

**Reset.** Leave the ask. You can veto or ignore later items. Stop the monitor with Ctrl+C.

## M5. Three clicks, one POST, one bot run

**Preconditions.** M4 works. The popup has an ask you can act on, or you can click Approve, then a different action the item lists, then Approve again if the popup still offers it. Three `PerformAction` calls within 10 seconds is the goal. They must be for the same bot.

**Commands.** Click three actions within 10 seconds. Wait about 20 seconds after the last click.

```bash
journalctl --user -u tetherbot -n 30 --no-pager
```

**Look for.**

- One line `webhook post bot=primary result=accepted` (your bot id). Not three.
- The bot's chat shows one run, not three.
- `tetherbotctl status` shows `queue: 0`.

**Reset.** Nothing.

## M6. A local 400, then backoff, then park

**Preconditions.** M3's slot works. You can change the secret and put the real URL back afterwards.

**Commands.** Start the fake server in its own terminal. It listens on `127.0.0.1` and always returns HTTP 400. It does not print the key.

```bash
python3 scripts/fake-webhook.py
```

It prints a URL like `https://127.0.0.1:8765/hook` and a `bundle:` path. Trust that bundle only for this check, then restart the bridge:

```bash
systemctl --user set-environment SSL_CERT_FILE=/run/user/UID/tetherbot-fake-webhook/bundle.pem
systemctl --user restart tetherbot
```

Use the bundle path the script printed. The bundle includes the normal system certificates plus this one-day certificate, so GitHub still works if you need it during the check.

Point the slot at the fake URL. At the prompts, paste the printed URL and any throwaway key, for example a short sentence you invent. Do not reuse the real webhook key.

```bash
tetherbotctl secret set primary-actions
```

Click one action in the popup, or send one from the terminal. Replace the item key if yours is different. The item must be `open` and must list `approve`.

```bash
gdbus call --session \
  --dest io.github.grokkinggrok.TetherBot1 \
  --object-path /io/github/grokkinggrok/TetherBot1 \
  --method io.github.grokkinggrok.TetherBot1.PerformAction \
  'primary/primary-20261017-01' 'approve' '{}'
```

Wait about 20 seconds for the first POST, then read the queue:

```bash
gdbus call --session \
  --dest io.github.grokkinggrok.TetherBot1 \
  --object-path /io/github/grokkinggrok/TetherBot1 \
  --method io.github.grokkinggrok.TetherBot1.GetQueue
```

**Look for.**

- The queue JSON has `"state": "pending"` and a `detail` that starts with `retry-after:`.
- The first retry is about one minute after the first POST (60 seconds, plus up to 10% jitter). Later waits are about 2 minutes, 4, 8, 16, then 30, then 30.
- After the 8th HTTP 400, the same action's `state` is `parked` and `detail` is `rate cap`. A notification title is `Webhook paused`.
- The full wait is about an hour and a half. You can confirm the first `retry-after` and leave the session logged in for the park, or stop after the first retry and note that the park was not waited out.
- The fake server's terminal only says `request handled`. It does not print the key.

HTTP 400 is treated as the shared rate cap. Whether a 400 body can also mean "the payload itself is invalid" is still **TBD, verify**. This server's body is `{"error":"fake rate cap"}`. Record the status you see if you later point the same check at the real routine.

**Reset.**

1. Stop the fake server with Ctrl+C.
2. Clear the temporary trust and restart:

```bash
systemctl --user unset-environment SSL_CERT_FILE
systemctl --user restart tetherbot
```

3. Store the real URL and key again with `tetherbotctl secret set primary-actions`.
4. Drop the parked action if one remains. The id is the `action_id` field from `GetQueue`:

```bash
gdbus call --session \
  --dest io.github.grokkinggrok.TetherBot1 \
  --object-path /io/github/grokkinggrok/TetherBot1 \
  --method io.github.grokkinggrok.TetherBot1.DropQueued \
  'a-THE-ID'
```

## M7. Wrong key, re-paste, queue drains

**Preconditions.** M3's real routine is in use again (M6's reset is done). Webhook sender is enabled. This check uses `tetherbotctl secret set`. The graphical dialog is M69. Either one stores the key. Neither one shows a stored key.

**Commands.** Store a wrong key on purpose. Paste the real **POST to** URL, then a key you invent that is not the routine's key.

```bash
tetherbotctl secret set primary-actions
```

Click one action, wait about 20 seconds, and read status:

```bash
tetherbotctl status
gdbus call --session \
  --dest io.github.grokkinggrok.TetherBot1 \
  --object-path /io/github/grokkinggrok/TetherBot1 \
  --method io.github.grokkinggrok.TetherBot1.GetQueue
```

**Look for.**

- Status is `degraded` and the reason is `re-paste key`.
- The action is `parked` in `GetQueue`. `tetherbotctl status` shows `queue: 0` and `parked: 1`. `queue:` is pending actions only. Parked actions stay in `GetQueue` and do not count as pending. They are not sent again until you store the real key or call `RetryParked`.
- A notification titled `Re-paste key`. The button does not open a dialog in this release. That is expected.
- The journal has a line `webhook post bot=<id> result=rejected_key status=<code>`. Write down that code. The bridge treats 401 and 403 as a bad key. Whether the live routine uses 401 or 403 is **TBD, verify**. If you see a different status, stop and note the number in the open checks. The line has no response body, no URL, and no key. Do not copy a response body into a chat.

Put the real key back. Paste the real URL and the real key at the hidden prompts:

```bash
tetherbotctl secret set primary-actions
```

**Look for.** The parked action is retried. After the coalesce and send, `GetQueue` is empty, `tetherbotctl status` is not stuck on `re-paste key`, and the bot's chat shows the action. This spends a bot run.

**Reset.** You already stored the real key. If an action is still parked, `DropQueued` it as in M6.

## M8. Offline click survives a reboot

**Preconditions.** M3's real webhook works. The extension is enabled. An item with a `done` action is visible, or use Approve if that is the action the item lists. The check wants one click while the network is down, then one send after the network returns, including across a reboot.

**Commands.**

1. Turn the network off (the system menu, Wi-Fi off, or unplug Ethernet). Leave the session logged in.
2. Click **Done** or **Approve** once.
3. Reboot. Log back in. Do not click the action again.
4. Turn the network on.
5. Wait about a minute.

```bash
tetherbotctl status
journalctl --user -u tetherbot -b --no-pager | tail -n 40
```

**Look for.**

- While offline, `tetherbotctl status` can say `offline`. The queue length is 1.
- After the network returns, one `webhook post` line with `result=accepted`, and one bot run. Not two.
- `queue: 0`.

**Reset.** Turn the network back on if it is still off.

## M10. A feed commit shows up within one poll

**Preconditions.** A private GitHub repository created from `template-repo/`. A fine-grained token for that one repository: Contents read and write, Metadata read, about 90 days. The bridge is running.

Rename `feed/primary.json` in that repository to `feed/<your-bot>.json` if your bot id is not `primary`, and set the `"bot"` field to the same id. Keep `"schema": "tetherbot/1"`.

In `~/.config/tetherbot/config.toml`:

```toml
[bridge]
mode = "full"

[adapters.github-poller]
enabled = true
remote = "https://github.com/OWNER/REPOSITORY.git"
branch = "main"
poll_seconds = 120
auth = "https-token"
```

The URL is the plain https URL. It must not contain a token or a password.

Before the first commit, the empty repository needs the feed pushed. An empty GitHub repository has no `main` branch until you push `feed/<bot>.json` from `template-repo/` yourself. The bridge does not create that commit.

The helper only answers for the configured remote path. Point this `config.toml` at the repository before any manual git use of the helper, and pass `-c credential.useHttpPath=true`:

```bash
git -c credential.helper= \
  -c credential.helper='git-credential-tetherbot --slot github-token' \
  -c credential.useHttpPath=true \
  ls-remote https://github.com/OWNER/REPOSITORY.git refs/heads/main
```

Do not put the token in that URL.

```bash
tetherbotctl secret set github-token
tetherbotctl enable repo
systemctl --user restart tetherbot
```

Paste the token only at the hidden `GitHub token:` prompt.

Wait until the clone exists:

```bash
ls ~/.local/share/tetherbot/repos
```

The directory name is the repository name. Then:

```bash
git -C ~/.local/share/tetherbot/repos/REPOSITORY config --get-all credential.helper
git -C ~/.local/share/tetherbot/repos/REPOSITORY remote get-url origin
```

**Look for.**

- `credential.helper` prints a blank line (the reset) and then a line ending in `git-credential-tetherbot --slot github-token`.
- `remote get-url` prints the plain https URL. The token is not in it.
- If status stays `degraded` on every poll, the reason is `ls-remote failed: auth` or `ls-remote failed: network`. The journal line is the same short reason. It does not include git's output or the token. `auth` means the helper could not supply the token (the configured path, the keyring, or the helper install). `network` means git could not reach the remote.
- Within one poll interval (120 seconds unless you set a shorter `poll_seconds`, minimum 60), the popup lists the sample ask.
- Commit a new item, or set `"notify": true` on a new item, in `feed/<bot>.json` and push it with your own git (not by putting the token in the remote). Within one poll, one notification appears. **Approve**, **Veto**, and **Snooze** work when the item lists those actions. Snooze stays on this machine. The notification has no Open chat button. A deep link to one bot chat is still an open item.

**Reset.** Leave the repository configured if you are going on to M11. To stop polling, `tetherbotctl disable repo`.

## M10a. A veto hides the item until the feed changes it

**Preconditions.** M10, and M4's webhook accepts actions. The popup shows a notify item whose actions include veto. Restart the bridge after installing this version (`systemctl --user restart tetherbot`). The popup reads the item list from the bridge, so this check does not need a log out. A log out and back in is needed only if you reinstalled the extension and want the shell to load that copy.

**Commands.** Veto the notify item from the popup or its notification. Wait until the action is accepted (about 20 seconds, the coalesce window).

```bash
systemctl --user restart tetherbot
tetherbotctl status
```

Open the popup again. Then, in the feed repository, edit that item: keep `"status": "open"`, set `updated_at` to a later time than the tap, and push.

Wait one poll.

**Look for.**

- The item disappears from the popup and the badge as soon as you tap Veto. The queue count includes it until the webhook accepts.
- The Bots row does not keep that item's title. Its summary is the feed's `status.summary` (for example `1 open ask.`). Last seen follows the feed file's `updated_at` (or `status.last_run` when that is later), not the item. The state dot follows `status.state`; `needs_you` is amber. The row updates from `PropertiesChanged` for `Bots` after a bridge restart. The new dot colors load with the extension, so they need a log out and back in after this version is installed.
- After accept, `queue: 0`. The item is still absent.
- After the bridge restart, the item is still absent.
- `desktop/state.json` in the clone has that item's `status` set to `dropped` and an `acted` object (`action` is `veto`). `feed/<bot>.json` is unchanged by the bridge.
- After the feed push, within one poll, the item is listed again.

**Reset.** Leave the repository configured.

## M11. An unknown schema fails closed and keeps the old items

**Preconditions.** M10. The popup is showing the sample ask.

**Commands.** In the private repository, change only the feed file's schema and push:

```json
"schema": "tetherbot/2"
```

Wait one poll interval.

```bash
tetherbotctl status
```

**Look for.**

- Status is `degraded`.
- The reason names `feed/<bot>.json`, says `unsupported schema tetherbot/2`, and says `update tetherbot`.
- The previous ask is still listed. It is stale: new fields from the `tetherbot/2` file are not invented, and the old item was not wiped.

**Reset.** Change the schema back to `tetherbot/1`, push, and wait one poll interval. On the rehearsal repo, commit in the checkout and push to the bare remote. A degraded feed does not slow the next poll: the fix shows up within `poll_seconds`, including when an earlier push was rejected. Status returns to `ok` when the file is readable again and nothing else is wrong. If the journal still says `push rejected`, the remote is not the bare repo from M4. Polling continues; desktop state is not updated until a push succeeds.

## M12. Lock the keyring

**Preconditions.** At least one adapter is enabled, so status is not `unconfigured`. M3 or M10 is enough. The bridge is running.

**Commands.** Lock the login keyring:

```bash
busctl --user call org.freedesktop.secrets \
  /org/freedesktop/secrets \
  org.freedesktop.Secret.Service \
  Lock ao 1 /org/freedesktop/secrets/collection/login
```

If a prompt path other than `/` comes back, a dialog may ask you to confirm. Confirm it. Wait a couple of seconds.

```bash
tetherbotctl status
```

**Look for.**

- Within a few seconds, status is `degraded` and the reason is `keyring locked`. This is the login collection. Another collection that is still open does not keep status at `ok`.
- `journalctl --user -u tetherbot -n 20 --no-pager` has a line `bridge degraded: keyring locked`.
- No new file appears under `~/.config/tetherbot` or `~/.local/state/tetherbot` that you did not create. The bridge does not write a plain-file copy of the token or the key. M13 checks that directly.
- Optional: click one action while the keyring stays locked. It remains `pending` with `attempts` 0. There is no `webhook post` line. Status stays `degraded` / `keyring locked`, and `queue:` is 1.

**Reset.** Unlock the login keyring. This asks for your login password in a dialog:

```bash
busctl --user call org.freedesktop.secrets \
  /org/freedesktop/secrets \
  org.freedesktop.Secret.Service \
  Unlock ao 1 /org/freedesktop/secrets/collection/login
```

Within a few seconds, `tetherbotctl status` leaves `keyring locked`. An action that was waiting goes out on the next send. Do not click it again.

## M13. Secret sweep

**Preconditions.** You have stored a webhook secret, a GitHub token, or both, using `tetherbotctl secret set`. The keyring is unlocked (M12's reset).

**Commands.** From the TetherBot clone:

```bash
python3 scripts/secret-sweep.py
```

The script reads the token and the webhook secret from libsecret. It searches:

- `~/.config/tetherbot` and the user unit
- `~/.local/state/tetherbot`
- `~/.cache/tetherbot`
- `~/.local/share/tetherbot/repos` (the clone, including `.git`)
- `dconf dump /`
- `journalctl --user`

**Look for.**

- The script prints `clean` and exits 0.
- It never prints the token, the key, or the URL. A problem line looks like `match: journal` or `match: clone`, with no secret text.
- Exit 2 means a command was missing (`dconf`, `journalctl`) or no secret was stored. Install the missing command and run it again. Do not treat a skip as a pass.
- If you see `match:`, that check fails. Do not open the matching file in a chat. Remove the value from that place (it should not have been written) and run the script again.

**Reset.** Nothing. The script only reads.

## M14. Extension install, dim, restore, no leftovers

**Preconditions.** M1. A graphical GNOME Shell 50 session on Wayland.

**Commands.**

```bash
scripts/install-extension.sh
```

`make install-extension` is the same script.

Log out and log back in. Wayland does not reload shell code until you do. Then enable the extension:

```bash
gnome-extensions enable tetherbot@grokkinggrok.github.io
```

You can also enable it in the Extensions app. The UUID is `tetherbot@grokkinggrok.github.io`.

**Look for.** A TetherBot indicator on the top bar. With the bridge running and an ask in the store, the menu lists bots, asks, and todos. With the bridge `unconfigured`, the icon is dimmed and the menu says the bridge is not running or not configured.

Stop and start the bridge:

```bash
systemctl --user stop tetherbot
```

Within about 2 seconds the indicator dims.

```bash
systemctl --user start tetherbot
```

The indicator comes back.

Disable the extension:

```bash
gnome-extensions disable tetherbot@grokkinggrok.github.io
```

**Look for leftovers.**

- The indicator is gone from the top bar.
- Looking Glass: press Alt+F2, type `lg`, press Enter. In the evaluator:

```js
Main.panel.statusArea['tetherbot@grokkinggrok.github.io']
```

That should be `undefined`. Close Looking Glass with Escape.

- The shell journal should not grow new TetherBot errors about a signal on a disposed actor after you disable:

```bash
journalctl --user -b /usr/bin/gnome-shell --no-pager | tail -n 80
```

**Reset.** Enable the extension again if you still want it. `scripts/uninstall.sh` removes the extension files. Log out and back in after an uninstall if the shell was still running the extension.

## M18. Chips on a rich todo

**Preconditions.** M14. The bridge is running and the extension is enabled. `feed/primary.json` has one open todo with three tags, a due time, priority 1, and a Markdown body. `tools/feed_write.py add-todo` can write that item. Restart the user service after installing a bridge that understands the new fields.

**Look for.**

- The popup row shows `#1`, a due chip, and three tag chips. The title is one line.
- Open TetherBot on that item. The window list and the detail pane show the same chips.
- The colors for a tag match in the popup and the window.

## M19. Search finds a word in the body

**Preconditions.** M18. The body contains a word that is not in the title.

**Look for.** Type that word in the popup search and in the window search. The todo appears in both. Asks stay in the popup. Clearing the search shows the todo list again.

## M20. Tag filter and quick views

**Preconditions.** M18, plus a second todo that has only one of the two tags, a bot-owned todo, a waiting todo, and one that is due today or overdue.

**Look for.**

- In the window, turning on two tag chips shows only the todo that has both.
- All, Mine, Bots, Waiting, and Today each match their rule.
- `@tag`, `due:today`, `due:overdue`, and `p:1` in either search box agree.

## M21. Markdown and a link

**Preconditions.** M18. The body has a heading, a list, a code span, and an `https` link.

**Look for.** The detail pane renders those. Clicking the link opens the default browser. An image in the body is not fetched. Raw HTML is shown as text.

## M22. Done and Undo

**Preconditions.** M18. The bot has an outbound route.

**Look for.**

- Done in the window or the popup turns that button into Undo. The menu stays open. Nothing is sent yet, and the footer does not say Queued.
- Undo before the shared bar ends brings that item back. Nothing is sent for it.
- When the bar ends, or the menu or the window closes, the pending rows are sent together. The Undo button is gone, so it does not send `reopen`.

## M23. A feed with no new fields

**Preconditions.** A todo written before tags and Markdown: no `tags`, no `body_format`, no `priority`.

**Look for.** The popup row is the title, the bot, and the due text, as before. The window still opens it and shows the body as plain text.

## M24. The window is a separate app

**Preconditions.** `scripts/install.sh` has been run. The extension is enabled.

**Look for.**

- Open TetherBot in the popup, and the same app in the app grid, both open one window. A second launch raises it.
- The extension does not spawn a process. The bridge launches the window.
- The window holds no secrets and makes no network requests. Links open only after a click.

**Reset.** None. Log out and back in after changing extension files. `systemctl --user restart tetherbot` is enough for a bridge-only change.

## M25. A new login starts the bridge

**Preconditions.** `scripts/install.sh` has been run on this machine before, so the unit was enabled. Re-run `scripts/install.sh` so an older `default.target` enablement moves to `graphical-session.target`. The extension is enabled.

**Look for.**

- Log out and back in. Do not run `systemctl start`.
- Within about 10 seconds the top-bar icon is active, not the inactive icon with "Bridge not running".
- `systemctl --user is-active tetherbot` prints `active`.

**Reset.** None.

## M26. A todo click opens the window quickly

**Preconditions.** M24. The bridge is running. Close the TetherBot window if it is open, and wait a minute so the process has exited.

**Look for.**

- Click a todo title in the popup. The window is on screen within about 1.5 seconds, first with a loading line if the list is not ready yet, then the item.
- Close the window and click another todo before a minute has passed. That open is immediate. The journal does not show a new window service for that second click.

**Reset.** None. Log out and back in after changing extension files. `systemctl --user restart tetherbot` is enough for a bridge-only change.

## M27. Start, pause, and stop from a todo

**Preconditions.** M24. One open todo is in the popup.

**Look for.**

- Start the timer from that todo's row. The top-bar button shows the time, and the row says Timing.
- Pause, Resume, and Stop work from the top of the popup.
- The todo shows a `tracked` chip in the popup and in the window.

**Reset.** None.

## M28. The time survives an extension restart

**Preconditions.** A timer is running. Note a phone stopwatch started at the same moment, or note the button's time.

**Look for.**

- Disable and enable the extension. The time matches.
- Restart a nested devkit shell while it runs. The time matches the phone within 2 seconds.

**Reset.** None.

## M29. The time survives a bridge kill

**Preconditions.** A timer is running.

**Look for.**

- `systemctl --user kill -s KILL tetherbot`. After the bridge returns, the time is still right.

**Reset.** None.

## M30. Logout keeps counting

**Preconditions.** A timer is running.

**Look for.**

- Log out for 5 minutes and log back in. The time includes those 5 minutes.

**Reset.** None.

## M31. A paused timer survives reboot

**Preconditions.** A timer is paused. Note the time.

**Look for.**

- Reboot. It is still paused at the same value.

**Reset.** None.

## M32. The timer file always parses

**Preconditions.** The bridge is running.

**Look for.**

- Kill the bridge in a loop while a script calls `tetherbotctl timer start`, `pause`, and `resume`. `~/.local/state/tetherbot/timer.json` is either absent or parses as JSON after each kill.

**Reset.** `tetherbotctl timer stop` if a timer is still there.

## M33. A clock change asks before the number is trusted

**Preconditions.** A timer is running. You can turn NTP off and back on.

**Look for.**

- Turn NTP off and set the clock back 1 hour. The button shows `--:--` and the amber triangle.
- Keep, Set time..., and Discard each do what they say.
- Turn NTP back on.

**Reset.** Confirm the clock is right before the next check.

## M34. Undo and Done record the right total

**Preconditions.** A todo timer has been running.

**Look for.**

- Stop, then Undo within 5 seconds. The recorded total goes back, and the timer is running again.
- Done on a timed todo records the time before the item is sent.

**Reset.** None.

## M35. A dead bridge hides the time

**Preconditions.** An approval is waiting and a timer is running, so the button shows the time and the dot.

**Look for.**

- Stop the bridge. The slash shows and the time hides. The popup says the saved time is safe.
- Start the bridge. The time and the dot come back.

**Reset.** None.

## M36. Each state has its own words

**Preconditions.** You can move the button through all clear, running, paused, approval, overdue, clock warning, and bridge down.

**Look for.**

- With Orca, focus the button in each state and hear the names in [STOPWATCH.md](STOPWATCH.md) section 10.
- Slash, triangle, pause bars, and dashes are distinguishable in grayscale. The red and blue corner dots share one shape; Orca names which one it is.

**Reset.** None.

## M37. The top bar has no seconds

**Preconditions.** A timer is running.

**Look for.**

- Under an hour the button reads `0m`, `5m`, or `41m`, with no leading zero and no seconds.
- At an hour or more it reads `1:05` or `12:40`.
- The popup clock may still show seconds.

**Reset.** None.

## M38. Edit a start that was forgotten

**Preconditions.** A timer is running or paused.

**Look for.**

- Edit start offers `-5m`, `-15m`, and `-30m`, and an `HH:MM` entry, in the popup and in the window.
- `-15m` adds about 15 minutes. The new total survives a bridge restart.
- A time in the future is refused. A start more than 24 hours ago is refused.

**Reset.** None.

## M39. The window closes

**Preconditions.** The TetherBot window is open.

**Look for.**

- The header has a close button, including when the window is narrow.
- Ctrl+W closes it. Escape closes it.

**Reset.** None.

## M40. Add the time to a todo

**Preconditions.** A timer is running and is not already on a todo. At least one open todo is in the list.

**Look for.**

- Add to a todo highlights the rows and offers Cancel. Clicking a row attaches the time. The window does not open.
- The same Attach timer button in the window does it while the timer is still running.
- Stop a timer that is not on a todo, then add it from the popup. The todo shows the tracked chip.

**Reset.** None.

## M41. A stopped timer stays until you deal with it

**Preconditions.** Stop a timer that is not on a todo.

**Look for.**

- Undo is there for about 5 seconds and then fades. The stopped time is still in the popup and on the top bar.
- Opening the window does not clear it. `~/.local/state/tetherbot/timer.json` is still there.
- Undo within 5 seconds resumes the timer and the time keeps counting.
- Dismiss removes it. After Dismiss, `timer.json` is gone and nothing new was recorded.

**Reset.** None.

## M42. Attach stays in pick mode, and the window has one titlebar

**Preconditions.** A timer is running and is not on a todo. The TetherBot window can open.

**Look for.**

- Add to a todo highlights the todo rows and shows Cancel. The highlight stays until you click a row or Cancel. The click attaches the time. The window does not open.
- Attach timer on the open todo puts that timer on it. The row says Timing.
- The window opens wide enough that the close button is on screen. There is one set of minimize, maximize, and close buttons. Making the window larger does not add a second set.
- Edit start in the popup is one row: the three quick buttons, a small time field, Set, and a close control.

**Reset.** None.

## M43. A second bot keeps the first feed

**Preconditions.** M10. `feed/primary.json` already has an open todo or ask. Install this version, then log out and back in so the shell loads the extension.

**Look for.**

- The existing primary items are still in the popup, labeled with a name rather than only the slug.
- Add `feed/notes.json` (or another id) with `"bot"` set to that id and one open todo. On the next poll, that todo appears and names its bot. `feed/primary.json` is unchanged.
- The bridge does not write either feed file.

**Reset.** Leave both files. M44 uses them.

## M44. Display names

**Preconditions.** M43. Two bots are in the feed.

**Look for.**

- `tools/feed_write.py status --name` on one bot changes the label in the popup, the window, and a notification. The file's `"bot"` value stays the slug.
- With no `--name` and no `display_name` in `config.toml`, the label is the slug with a capital letter (`notes` shows as `Notes`).
- Setting `display_name` under `[bots.<id>]` in `config.toml` wins over the name in the feed. The slug in item keys does not change.

**Reset.** None.

## M45. The popup stays one line when every bot is fine

**Preconditions.** M43. More than one bot, and each is idle or working with no open ask.

**Look for.**

- The Bots section is one line, such as `2 bots · all ok`, however many healthy bots you add.
- Make one bot `needs_you` or stale, or give it an open ask. That bot gets its own row, and the summary turns amber and names it. A bot in state `error`, or a bridge failure, turns that same line red.
- With only one bot configured, the section is that bot's row, as before, and there is no summary line.

**Reset.** None.

## M46. Popup order and the window Bots tab

**Preconditions.** M45. Log out and back in if the extension was updated after the last login.

**Look for.**

- The popup order is Timer, Todos, Asks, Bots, then Open TetherBot, the status line, Sync now, and Settings.
- Clicking the bot summary opens the TetherBot window on the Bots tab. Every bot is listed with its name, last seen, next run, and open todo count.
- Typing in the name filter hides the other bots. Clicking a bot filters the todo list to that bot, the way a tag chip does.

**Reset.** None.

## M47. The timer still behaves after the new popup

**Preconditions.** M41 still matches this install. Log out and back in once with a timer running or paused.

**Look for.**

- The time is still there after login, and a paused timer is still paused.
- Undo after Stop resumes, including from paused, and does not lose the counted time.
- Add to a todo and Attach timer still attach. A stopped timer that is not on a todo survives opening the window and offers Dismiss.

**Reset.** Dismiss or assign the timer when you are done.

## M48. A bot with no webhook slot stays up

**Preconditions.** M14. At least two bots are in `config.toml`. One of them has no `webhook_slot`.

**Look for.**

- `tetherbotctl status` stays `ok` (or the state it had before that bot was added). It does not say `failed_closed` because a slot is missing.
- That bot still appears, under its display name. Its Done and Approve buttons are hidden.
- A slot value that is not a short lowercase name is ignored for that bot only. The other bots still load, and the bridge stays up.

**Reset.** None.

## M49. Sync now fetches immediately

**Preconditions.** M10. The repo adapter is running.

**Look for.**

- Add a todo in the feed, then click Sync now before the regular poll. The menu item says Syncing…, then Updated, and the new todo shows without waiting for the next interval.
- A second click within about 30 seconds does not start another fetch.

**Reset.** None.

## M50. The timer names its bot with a chip

**Preconditions.** M40. A timer is running on a todo.

**Look for.**

- Under the clock, the todo title and the bot name sit on one line. The bot name is a chip, the same shape as the bot chip on a todo row.
- The title, the chip, and the buttons have space between them.

**Reset.** None.

## M51. The toolbar number is only the timer

**Preconditions.** M14. Log out and back in after installing this version.

**Look for.**

- The top bar shows no count of todos, asks, or bots. The only number is the timer, such as `25m` or `1:05`, and it is absent when no timer is showing.
- With an open todo and no ask, the icon carries a small red corner dot and no digit.
- When a bot needs attention, or an ask is open, that corner dot is blue instead. The tooltip describes that in words and does not give a count.

**Reset.** None.

## M52. The bot summary stays readable

**Preconditions.** M45. The compact summary is the attention line, and the row is highlighted.

**Look for.**

- The summary text is easy to read on the highlighted row. A warning is light amber on a darker amber. An error or a bridge failure is light on a darker red.

**Reset.** None.

## M53. Each bot row shows its state

**Preconditions.** M46. One bot is `needs_you`, `error`, or stale.

**Look for.**

- On the window Bots tab, that bot's row has a colored dot and the same status summary as its popup row.
- The list still scrolls when there are more bots than fit.

**Reset.** None.

## M54. Dates use local time

**Preconditions.** M18. Open a todo whose `created` and `updated_at` fall on the previous local calendar day when read as UTC.

**Look for.**

- The Created chip uses the local calendar day.
- The detail footer names the bot, the routine, and a short local time, such as `Oct 19, 9:40 PM`. It does not show a raw `T` timestamp.

**Reset.** None.

## M55. The timer chip sits on the left

**Preconditions.** M50. A timer is running on a todo that has a bot name.

**Look for.**

- Under the clock, the bot chip is first, at the left, and the todo title follows it on the same line.
- A long title stays on that line. The chip does not jump to the far edge.

**Reset.** None.

## M56. The top bar hugs the timer

**Preconditions.** M51. Log out and back in after installing this version.

**Look for.**

- The panel button is only as wide as the icon plus the timer text. There is no empty stretch after `1:29` or `5m`.
- `5m` is narrower than `41m`, and `41m` is narrower than `1:05`.
- While the timer runs inside one shape, the button does not jitter as the digits change.

**Reset.** None.

## M57. An open window follows a renamed bot

**Preconditions.** M46. The TetherBot window is already open.

**Look for.**

- Change a bot's display name in the feed and sync. The popup and the open window both show the new name. Closing the window is not required.
- The Bots tab shows the new name, the status dot, and the summary. Todo rows show the new name on their chip.

**Reset.** None.

## M58. The panel icon follows the shell

**Preconditions.** M14. The panel icons are larger than the shell default, the way a 4K display is set up. Log out and back in after installing this version.

**Look for.**

- The TetherBot icon is the same height as the other status icons.
- With an open todo, the red corner dot grows with the icon. With an ask waiting, the blue dot grows with it. The button does not get wider.
- The only number in the top bar is still the timer.

**Reset.** None.

## M59. The icon reads as a face

**Replaced by M65 and M66.** The face takes the shell's status-icon color, and both eyes are checked at the panel size.

**Preconditions.** M58.

**Look for.**

- The icon has two eyes and a small smile. It does not read as a piece of fruit.
- The corner dot still sits in the bottom-right and stays readable.

**Reset.** None.

## M60. Each Done keeps five seconds, in place

**Replaced by M68.** One shared bar covers every unsent row. A new Done restarts that bar instead of keeping a separate five seconds.

**Preconditions.** M22. At least three open todos are on screen in the popup.

**Look for.**

- Done on a middle row. The row stays in that spot and the button becomes Undo. A bar on Undo starts full and shrinks.
- About four seconds later, Done on another row. That Undo bar starts full. The first row does not vanish early. Each one lasts about five seconds from its own click.
- The same bar appears on Undo after Stop, in the popup.

**Reset.** Undo both, or let them expire.

## M61. An expiring row does not jump under the pointer

**Replaced by M67.** The action is sent when the bar ends, even while the pointer stays on the list. The row keeps its place until the pointer leaves, and the Undo button is removed.

**Preconditions.** M60. The pointer is over the todo list in the popup, and over the list in the window.

**Look for.**

- Let an Undo expire while the pointer stays on the list. That row keeps its place until the pointer leaves. The row under it does not slide up into the click.
- Move the pointer off the list. The expired row leaves.
- In the window, Done on a middle row. The row stays there with an Undo bar. A second Done, a few seconds later, gets its own full bar. Expiring while the pointer is over the list does not shift the other rows.

**Reset.** None.

## M62. The primary bot stays first

**Preconditions.** M46. More than one bot is configured, including `primary`.

**Look for.**

- In the window Bots tab, `primary` is the first row. The other bots stay in alphabetical order under it.
- The popup's attention rows, when several need attention, use that same order.

**Reset.** None.

## M63. Several bots can share one webhook slot

**Preconditions.** M4. Two bots in `config.toml` both set `webhook_slot` to the same name, for example `primary-actions`. The secret is stored once, for that slot.

**Look for.**

- Done on a todo for each bot sends. The bridge status stays ok.
- `tetherbotctl status` does not print a missing-secret line for either bot.

**Reset.** None.

## M64. A missing secret stays on that bot

**Preconditions.** M4. Two bots. `primary` has `webhook_slot = "primary-actions"` and that secret is stored. The other bot has its own slot, and that slot has no stored secret.

**Look for.**

- Done on the other bot still sends, and its row does not say the secret is missing. A bot with no stored secret uses the primary bot's slot.
- Remove the primary secret as well, and store a secret only for a third bot's own slot. The bot with no secret shows `webhook secret is not stored` on its row. Done on that bot waits. Done on the bot that has its own secret still sends. The bridge status stays ok.

**Reset.** Store the primary secret again.

## M65. The panel icon takes the shell color

**Preconditions.** M58. The other status icons use the theme's symbolic color. Log out and back in after installing this version.

**Look for.**

- The TetherBot face is the same color as the other status icons, including their accent. It is not white, and it is not a dark filled block.
- Change the desktop accent. The face changes with the other status icons.
- With the bridge stopped, the face is dimmer and carries a slash. The slash uses that same icon color.
- With an open todo, a small red dot sits in the bottom-right corner. With an ask waiting, that dot is blue. Neither dot takes the accent. M75 checks that.
- The only number in the top bar is still the timer.

**Reset.** None.

## M66. Both eyes stay visible

**Preconditions.** M65. Also try a larger panel icon size, if the shell lets you change it.

**Look for.**

- The face shows two eyes and a small smile at the normal panel size and at the larger size.
- The eyes are not clipped off, and they are not the same color as an empty face.
- With an open todo, the red corner dot stays readable and the eyes stay clear of it. With an ask waiting, the blue dot does too.

**Reset.** None.

## M67. Done sends when the bar ends

**Preconditions.** M22. The popup is open, the pointer stays over the todo list, and at least one open todo is on screen.

**Look for.**

- Done turns that button into Undo. A bar starts full and shrinks. The footer does not say Queued while the bar is running.
- Leave the pointer on the list until the bar ends, about 5 seconds. The action is sent then. The footer shows Queued for that row. The Undo button disappears, and it does not grow wider and stay.
- That row keeps its place until the pointer leaves the list. Moving the pointer off the list removes the row.
- In the window, Done on a middle row, then leave the pointer on the list until the bar ends. The button is gone, the row stays until the pointer leaves, and the action has been sent.

**Reset.** None.

## M68. One shared bar, one batch

**Preconditions.** M67. At least three open todos are on screen.

**Look for.**

- Done on one row. About two seconds later, Done on another. Both bars jump back to full and shrink together.
- Undo one of them. That row comes back as an open todo, and nothing is sent for it. The other row keeps the same bar.
- Let the bar end with the menu still open. The remaining rows queue together. The footer shows one Queued count for all of them, and the bot receives those clears in one run.
- Done on two rows, then close the menu before the bar ends. Nothing is queued yet. M77 checks that Undo still works and that the batch waits for the bar. Closing the window with pending rows still sends that batch.

**Reset.** Undo a pending row if you do not want it sent.

## M69. Settings opens, and a stored key stays hidden

**Preconditions.** M14. Log out and back in after installing this version so the prefs window loads. The bridge is running. At least one bot has a webhook slot. A key may already be stored with `tetherbotctl secret set`.

**Look for.**

- The top-bar menu's Settings item opens a TetherBot window, not an empty page.
- Poll interval shows 120 until you change it. Undo timer shows 5 until you change it.
- Each webhook slot has **Set up keys…** or **Replace keys…**. The GitHub token has the same kind of button. The label is **Replace keys…** only when that slot is already stored.
- The button opens a separate window. The fields are empty. A stored URL or key is not shown. Cancel closes it and leaves the stored key in place.
- The only number in the top bar is still the timer.

**Reset.** None. Leave the keys where they were.

## M70. Poll interval stays inside the old bounds

**Preconditions.** M69. `github-poller` is enabled and a feed edit is easy to make.

**Look for.**

- The poll spin does not go below 60 or above 900.
- Set it to 60. Edit the feed and push. The desktop shows the edit within about a minute without Sync now.
- Set it back to 120.

**Reset.** Leave the interval at 120.

## M71. Undo length is the same in the popup and the window

**Preconditions.** M69. At least one open todo is on screen. The default undo length is 5 seconds.

**Look for.**

- Set the undo timer to 10. Done in the popup keeps the bar for about 10 seconds. Undo before it ends sends nothing.
- Done in the window keeps the bar for about the same 10 seconds.
- Set the undo timer back to 5. The next Done in either place uses the shorter bar.
- The top bar still has no number except the timer.

**Reset.** Leave the undo timer at 5. Undo a pending row if you do not want it sent.

## M72. Notifications can be turned off for one bot

**Preconditions.** M69. Two bots, each able to publish an item with `notify` set.

**Look for.**

- Turn notifications off for one bot. A new item from that bot does not raise a notification. The other bot still does.
- The bot row for the quiet bot is still in the popup and the window.
- Turn notifications back on. A later new item from that bot notifies again.

**Reset.** Leave notifications on for every bot.

## M73. A hidden bot stays out of the popup and the window

**Preconditions.** M69. Two bots, each with an open todo or ask.

**Look for.**

- Hide one bot. Its todos, asks, and row disappear from the popup and from the window. The other bot stays.
- The hidden bot's items do not come back when you search or switch the window's bot filter.
- Show that bot again. Its row and items return.
- The top bar still has no number except the timer.

**Reset.** Leave every bot shown.

## M74. Reset to defaults restores the feed check and the undo timer

**Passed.** Reset to defaults restores the feed check and the undo timer.

**Preconditions.** M69. Change the feed check and the undo timer first (M70 and M71). Leave one bot hidden or its notifications off, and leave a key stored, so those can be checked afterward.

**Look for.**

- The Feed section has **Reset to defaults**.
- Press it. The feed check returns at once to 120, or to `poll_seconds` from `config.toml` when that is set. The undo timer returns at once to 5.
- Stored keys stay stored. The GitHub token button stays **Replace keys…** when that token was already stored. Hidden bots stay hidden. Notification switches stay as they were.
- The top bar still has no number except the timer.

**Reset.** None. Set the feed check or the undo timer again only if a later check needs a different value.

## M75. A small corner dot marks attention

**Passed.** The corner badge is in place, and blue for asks was confirmed.

**Preconditions.** M65 and M66. An open todo is on screen, and either an ask is open or a bot needs attention. Log out and back in after installing this version. Try a larger panel icon size if the shell lets you change it.

**Look for.**

- With only an open todo, the face matches the other status icons, including their accent, and both eyes stay visible. A small filled red dot sits in the bottom-right corner. It overlaps the face only in that corner. There is no ring.
- With an ask waiting, or a bot that needs attention, the face stays that accent color and the corner dot is blue. An ask and an open todo together still show only the blue dot.
- The dot is about a quarter of the icon, with a thin dark outline. It grows when the panel icon grows. The top-bar button does not get wider.
- Change the desktop accent. The face changes with the other status icons. The red dot stays red and the blue dot stays blue.
- With the bridge stopped, the face is dimmer and the slash uses the icon color. There is no colored dot.
- The only number in the top bar is still the timer.

**Reset.** None.

## M76. One new item raises one notification

**Passed.** One new item raises one notification.

**Preconditions.** M10. The bridge is running. You can add one open item, with `notify` set, to `feed/<bot>.json` and push it. The item can have a due date. It should not already be in the feed.

**Look for.**

- The desktop shows one notification for that item. The title and the body appear once.
- The same item is still only once in `feed/<bot>.json`.
- Restart the bridge with `systemctl --user restart tetherbot`. That item does not raise another notification. A later new item still does.

**Reset.** None. Leave the item, or remove it from the feed if you do not want it.

## M77. Popup Done waits for the undo bar

**Passed.** Done sends when the undo bar ends.

**Preconditions.** M67 and M68. At least two open todos are on screen in the popup. The undo timer is 5 seconds.

**Look for.**

- Done on two rows. Both bars are full and shrink together. Close the menu before the bar ends. The footer does not say Queued for those rows, and the bot has not received them.
- Open the menu again before the bar ends. Both rows are still there with Undo. Undo one of them. Nothing is sent for that row.
- Leave the other row until the bar ends, with the menu either open or closed. It is sent then, and not before. The footer shows Queued once the bar has ended.
- Done on one row and leave the menu open, with the pointer on the list, until the bar ends. It is sent while the menu is still open. That row keeps its place until the pointer leaves.

**Reset.** Undo a pending row if you do not want it sent.

## M78. Edit tracked time on a todo

**Passed.** The tracked total can be edited, and deleting a record asks first.

**Preconditions.** A todo already has tracked time. Open it in the TetherBot window. Log out and back in after installing this version.

**Look for.**

- The detail pane shows the tracked total as a short time, such as `1:42:00`, and a Set button. Each saved record is a short row with a delete button.
- Change the total and press Set. The chip on the row and in the detail pane matches the new total. Close the window and open it again. The total is still the new one.
- The records still add up to that total. A direct edit shows as its own adjustment record.
- Delete asks first. Cancel leaves the record. Confirm removes it, and the total matches the records that remain.
- The top bar still has no number except the timer. Nothing about the edit is sent to the bot.

**Reset.** Set the total back if you want the old amount.

## M79. Needs attention is amber

**Passed.** Needs attention is amber. An error or a bridge failure stays red.

**Preconditions.** M45. More than one bot. One bot needs attention and is not in state `error`. The bridge is running.

**Look for.**

- The Bots summary names that bot and is yellow or amber, not red.
- Put a bot in state `error`, or stop the bridge so the summary is a bridge failure. That line is red.
- A healthy summary stays the normal color.
- The corner dot is unchanged: red for an open todo, blue for an ask or a bot that needs attention.

**Reset.** Restore the bot state.

## M80. Stop timer on the open todo

**Passed.** Stop timer on the open todo stops a running or paused timer.

**Preconditions.** M37. A timer is running on an open todo. That todo is open in the TetherBot window.

**Look for.**

- The detail pane shows **Stop timer**, and the button can be pressed. It does not say Timing, and it is not disabled.
- Press Stop timer. The timer stops, the tracked total includes that session, and the button says **Start timer** again.
- Start timer on that same todo. The button returns to **Stop timer**. Pause it. The button still says **Stop timer** and still stops it. The row in the list can still say Timing.
- The top bar still has no number except the timer.

**Reset.** Stop the timer when you are done.

## M81. Copy the title, the body, or both

**Passed.** The copy icons copy the title or the body, and Copy Todo copies both.

**Preconditions.** An open todo has a title and a body. Open it in the TetherBot window.

**Look for.**

- A copy icon beside the title copies only the title. Paste somewhere else and check that the body is not included.
- A copy icon beside the body copies only the body. The title is not included.
- **Copy Todo** copies the title and the body, with a blank line between them.
- The top bar still has no number except the timer.

**Reset.** None.

## M82. Completed todos stay for the history window

**Passed.** History filtering updates live, and Reset to defaults leaves it alone.

**Preconditions.** Log out and back in after installing this version, so the settings schema loads. Settings shows Completed todos, on, with 1 and Years. Have one todo marked done on the desktop, and one the bot closed (`status` `done` in the feed). Have a dropped or vetoed item, or veto one during the check.

**Look for.**

- Show done in the window lists the desktop-done todo and the bot-closed todo.
- The dropped item is not in that list. An ask is not in that list. An item removed from the feed is not listed.
- Set the window to 1 hour. A todo completed longer ago than that disappears from Show done. It is still in the bot's feed file. Set the window back to 1 year and it shows again.
- Turn Keep completed todos off. Show done lists no done todos. Open todos stay.
- Reset to defaults does not change the history toggle, the number, or the unit.
- The top bar still has no number except the timer.

**Reset.** Turn history back on, amount 1, unit Years, if you changed it.

## M83. Enter sets the start time

**Preconditions.** A timer is running or paused. Open Edit start in the top-bar popup, and again in the TetherBot window.

**Look for.**

- The row has `-5m`, `-15m`, `-30m`, a time field, and Set.
- Type a time such as `8:29` and press Enter. The start changes the same way it does when you click Set.
- A time that is not `HH:MM` shows the same hint as clicking Set, and the timer does not change.
- The top bar still has no number except the timer.

**Reset.** None.

## M84. Done with the pointer left on the row

**Preconditions.** The TetherBot window is open on a todo list. The undo timer is at its default, about 5 seconds.

**Look for.**

- Click Done on a row and leave the pointer where it is, over that row.
- The row switches to Undo. When the undo time ends, the row leaves the list.
- Click Done on another row, then click a different row while the undo time still runs. When the time ends, the first row leaves. The window does not crash.
- The window stays open. It does not close, freeze, or disappear while the pointer is still there.
- The top bar still has no number except the timer.

**Reset.** Undo the todo if you want it back, before the bar ends.

## M85. How many names a month and a year

**Preconditions.** Log out and back in after installing this version, so the settings schema loads. Open Settings.

**Look for.**

- The Completed todos description does not say that a month is 30 days or that a year is 365 days.
- The How many row says `1 month = 30 days, 1 year = 365 days`.
- The top bar still has no number except the timer.

**Reset.** None.

## M86. The window opens at the list's height

**Preconditions.** Open the TetherBot window with a short todo list, then again with enough todos to scroll.

**Look for.**

- A short list opens the window tall enough for those rows, the header, and the toolbar, and no taller. The window is still at least as tall as before this change.
- A long list stops at the monitor's usable height. The extra rows scroll.
- Drag the window to a different height. Leave it open and let the list refresh. It stays at the height you set.
- The top bar still has no number except the timer.

**Reset.** None.

## M87. The last row is fully on screen

**Preconditions.** Log out and back in after installing this version, so the window process is the new one. Open the TetherBot window with a list that fits on the screen, and again with more todos than fit.

**Look for.**

- When the list fits, the last row is fully visible, including the space under it. The window edge does not cut through that row.
- The header bar is fully visible.
- A longer list stops at the monitor's work area, below the top bar. The rows past that scroll.
- The window is still at least as tall as before.
- Drag the window to a different height. It stays there while the list refreshes.
- The top bar still has no number except the timer.

**Reset.** None.

## M88. The window opens at the upper right

**Preconditions.** Log out and back in after installing this version, so the extension reloads. The TetherBot window is closed.

**Look for.**

- Open the window. It sits in the upper-right corner of the work area, below the top bar, with its right edge against the work area.
- Drag it somewhere else. Leave it open and let the list refresh. It stays where you put it.
- Close it and open it again. It returns to the upper-right.
- Settings does not jump to that corner.
- The top bar still has no number except the timer.

**Reset.** None.

## M89. Done with note reaches the bot and closes the todo

**Preconditions.** An open todo whose bot has an outbound route. The TetherBot window is open on that todo.

**Look for.**

- The detail pane has a Note field under the body, and a Done with note button next to Done.
- Type a short note. Press Done with note. The todo closes the same way Done does: the row shows the undo bar, and after that bar ends the todo is gone.
- The bot receives a done action for that item. The action includes `note` with the text you typed. `args` stays empty.
- Undo before the bar ends. Nothing is sent.
- Plain Done on another todo sends `done` with no `note` field.

**Reset.** None.

## M90. Done with note stays disabled while the note is empty

**Preconditions.** The window is open on a todo that can be marked done.

**Look for.**

- With Note empty, Done with note is disabled. Done stays enabled.
- Spaces only leave Done with note disabled.
- Typing a note enables Done with note. Clearing the field disables it again.
- Done still closes the todo without a note.

**Reset.** None.

## M91. The wider window still fits and opens at the upper right

**Preconditions.** This version is installed. If the window does not already open at the upper right, log out and back in once so the extension reloads. Open the window with a short list, and again with more todos than fit.

**Look for.**

- The window is wider than before, and the Note field is comfortable to type in.
- When the list fits, the last row is fully visible, including the space under it. The window is still at least as tall as its minimum.
- A longer list stops at the monitor's work area. The rows past that scroll.
- The window opens at the upper-right of the work area, below the top bar, with its right edge against the work area.
- Drag it somewhere else. It stays. Close it and open it again. It returns to the upper-right.
- Settings does not jump to that corner.
- The top bar still has no number except the timer.

**Reset.** None.

## M92. The detail buttons stay in place

**Preconditions.** The TetherBot window is open on an open todo that can be marked done. Start timer and Attach timer are in the button row.

**Look for.**

- The row is Done, Done with note, Start timer, Attach timer, Copy Todo, and Ask the bot about this. A button that does not apply is disabled. It is still in that spot.
- Press Done. Undo takes the Done slot. Done with note stays beside it, disabled. Start timer, Attach timer, Copy Todo, and Ask the bot about this do not move, and none of them appears or disappears.
- Undo. The row returns to the same buttons in the same places.
- Type a note and press Done with note. Undo takes the Done with note slot. Done stays in its slot, disabled. The other buttons stay put.
- Undo again. The row matches the start of this check.

**Reset.** None.

## M93. The undo bar shrinks toward the middle

**Preconditions.** An open todo. The toolbar menu and the TetherBot window are both available. Log out and back in if the menu's undo bar has not reloaded since this version was installed.

**Look for.**

- In the window, press Done. The Undo button's bar starts full and shrinks toward the middle, from both ends. It does not stay anchored to the left.
- The same shrink is on a Done with note Undo button, and on the Undo button in a list row.
- The toolbar menu's Undo bar shrinks the same way.

**Reset.** None.

## M94. Done does not crash when the receiver is unreachable

**Preconditions.** An open todo whose bot has an outbound route. The webhook receiver is stopped, or the network path to it is down. The TetherBot window is open.

**Look for.**

- Press Done and leave the pointer on that row until the undo bar ends.
- The window does not crash.
- The row is not destroyed under the pointer. It stays until you move the pointer away.
- After that, the todo is still listed if the action never reached the bot. If the bridge already queued it, the row hides the way a normal Done does, and it can come back when delivery fails.
- The top bar still has no number except the timer.

**Reset.** Restore the receiver or the network when you are done with this check.

## M95. Detail buttons stay a normal height and on screen

**Preconditions.** This version is installed. Reopen the TetherBot window after the old window process exits. A logout is not required. Open an open todo. Look at the default window size, then shrink the window to its minimum width.

**Look for.**

- Done, Done with note, Start timer, Attach timer, Copy Todo, and Ask the bot about this are normal single-line buttons. They do not stretch down to fill the pane. The body text takes the extra vertical space.
- Each button is only as wide as its label. They are not forced to one shared width.
- At the default width and at the minimum width, all six are fully visible. Nothing is cut off. If they do not fit on one line, the rest wrap to a second line.
- Press Done. Undo takes the Done slot and the other buttons stay in place. Undo again. The row matches the start of this check.
- The top bar still has no number except the timer.

**Reset.** None.

## M96. Detail buttons are evenly spaced

**Preconditions.** This version is installed. Reopen the TetherBot window after the old window process exits. A logout is not required for this check. Open an open todo. Look at the default window size, then shrink the window to its minimum width.

**Look for.**

- The gap between Done and Done with note matches the gap between the other buttons on that line. Done, Done with note, Start timer, Attach timer, Copy Todo, and Ask the bot about this keep their own widths.
- If the six do not fit on one line, the rest wrap, and the gaps on each line still match.
- Press Done. Undo takes the Done slot. Start timer and the buttons after it stay where they were. Undo again. The row matches the start of this check.
- The buttons stay one line tall. The body still takes the extra vertical space.

**Reset.** None.

## M97. A copied line is kept

**Preconditions.** Log out and back in after this version is installed. The bridge is running. Clipboard history is on in Settings. The cap is the default, 50.

**Look for.**

- Copy a short plain-text line from a text editor.
- Open the clipboard icon in the top bar. The line is in the menu. The icon has no count.
- The TetherBot window's Clipboard page lists the same line.

**Reset.** Use M102 when you want the line gone.

## M98. The panel menu copies an entry back

**Preconditions.** M97. The copied line is still in the menu.

**Look for.**

- Click the line in the clipboard menu.
- Paste into a text editor. The same line comes back.
- The menu does not type into the editor by itself.

**Reset.** None.

## M99. The window can search and delete

**Preconditions.** M97. Copy a second, different line so two entries are listed.

**Look for.**

- Open the Clipboard page. Both lines are listed.
- Type part of one line into Search clipboard. The other line drops out of the list.
- Clear the search. Both lines are back.
- Press Delete on one line. That line is gone. The other remains.
- Press Copy on the remaining line, then paste into a text editor. That line comes back.

**Reset.** None.

## M100. A password-manager copy is skipped

**Preconditions.** M97. A password manager is running. Its window class is one of the default skipped apps, or it marks the copy with `x-kde-passwordManagerHint` or a concealed clipboard type.

**Look for.**

- Copy a password from that app.
- The clipboard menu and the Clipboard page do not gain that password.
- A normal line copied from a text editor still shows up.

**Reset.** None. Do not write the password down in a note.

## M101. An excluded app is skipped

**Preconditions.** M97. Settings, Clipboard, Skip these apps includes a window class you can focus, in addition to the password managers already listed. Use a class such as the text editor's own class for this check, then put the password managers back.

**Look for.**

- Focus that app and copy a line.
- The line does not appear in the clipboard menu or on the Clipboard page.
- Focus a different app that is not on the list and copy a line. That line does appear.

**Reset.** Put the Skip these apps field back to the password-manager list.

## M102. Clear removes the history

**Preconditions.** At least one line is in the clipboard history.

**Look for.**

- On the Clipboard page, press Clear history and confirm. The list is empty.
- A pinned line stays. M109 covers pin.
- The clipboard menu says nothing is copied yet when nothing is pinned.
- The feed files are unchanged.

**Reset.** None.

## M103. The toggle stops new copies

**Preconditions.** M97. Turn Remember copied text off in Settings.

**Look for.**

- Copy a new line from a text editor. It does not appear in the menu or on the Clipboard page.
- Lines that were already saved stay until you clear them.
- Turn Remember copied text back on. The next copy is saved again.

**Reset.** Leave Remember copied text on unless you want it off.

## M104. Clipboard text stays off the feed

**Preconditions.** M97. The feed check is enabled, or you can inspect the local bridge state without waiting for a push.

**Look for.**

- Copy a distinctive line that is not a password and not already a todo title.
- Wait one feed check, or look at the local state directory.
- The line is in `clipboard.json` under the TetherBot state directory. It is not in a feed file, not in `desktop/`, and not in a webhook body.
- The top bar still has no number except the timer. The clipboard icon has no count.

**Reset.** Clear the history with M102 if you do not want to keep the line.

## M105. A Chrome password copy is not kept

**Preconditions.** Log out and back in after this version is installed. Clipboard history is on. In Settings, Password-like copies is Skip, which is the default. Use Chrome or Chromium's built-in password manager for the copy. Do not use a separate password-manager app for this check.

**Look for.**

- Copy a saved password from that browser's password manager.
- The clipboard menu and the Clipboard page do not show that password.
- Run `tetherbotctl clipboard-debug`. It prints the MIME types the browser offered, `result: skipped-lookalike`, and `reason: password lookalike`. It does not print the password.
- On Wayland and GNOME, current Chrome and Chromium offer ordinary text targets for that copy, such as `text/plain`, `text/plain;charset=utf-8`, `UTF8_STRING`, `STRING`, and `TEXT`, and sometimes `chromium/x-source-url`. They do not set `x-kde-passwordManagerHint`, a concealed type, or `application/x-chromium-*-sensitive`. The password-like rule is what skips the copy. If a future version does set a sensitive or confidential type, the result is `skipped-sensitive` instead, and the password is still not kept.
- Copy a normal sentence from a text editor. That sentence still appears.

**Reset.** None. Do not write the password down.

## M106. Ordinary text is not treated as a password

**Preconditions.** M105. Password-like copies is still Skip.

**Look for.**

- Copy a sentence with spaces. It is kept.
- Copy a URL such as `https://example.com/notes`. It is kept.
- Copy a file path. It is kept.
- Copy a number such as `12345678`. It is kept.
- Copy a short word such as `hello`. It is kept.
- Copy a file name such as `README.md`, and an email address. Both are kept.
- Copy one line with no spaces, 8 to 128 characters, mixing at least three of lowercase, uppercase, digits, and symbols, that is not a URL, a path, or a number. It is not kept.
- `tetherbotctl clipboard-debug` says `skipped-lookalike` for that line and does not print it.

**Reset.** None. Do not write a real password down. A made-up line is enough for the last step.

## M107. Hide a password-like copy for 30 seconds

**Preconditions.** M105. In Settings, set Password-like copies to Hide for 30 seconds.

**Look for.**

- Copy a made-up password-like line, or a password from Chrome's password manager.
- The clipboard menu and the Clipboard page say Hidden password. They do not show the text.
- Type part of that text into Search clipboard. The row does not appear. Clear the search. The Hidden password row is back.
- Press Copy and paste into a text editor. The text comes back. The list still says Hidden password.
- Wait 30 seconds. The row disappears from the menu and from the Clipboard page.
- That text is no longer in `clipboard.json`.
- Set Password-like copies back to Skip. The next password-like copy is not kept.

**Reset.** Leave Password-like copies on Skip.

## M108. The debug command stays on this machine

**Preconditions.** M105. Copy one more ordinary line so the last offer is fresh.

**Look for.**

- `tetherbotctl clipboard-debug` prints `result:`, `reason:`, `mimes:`, and `wm_class:`.
- The copied text is not in that output.
- The copied text is not in the bridge log, not in a feed file, and not in a webhook body.

**Reset.** Clear the history with M102 if you do not want to keep the ordinary line.

## M109. Pin keeps an entry

**Preconditions.** Log out and back in after this version is installed, then open the TetherBot window. M97. Clipboard history is on. In Settings, set How many entries to 2 for this check.

**Look for.**

- Copy three ordinary lines from a text editor.
- In the clipboard menu, press the pin on the oldest line. That press does not copy the line. The pin stays solid, not faded.
- Copy one more ordinary line. The pinned line is still in the menu and at the top of the Clipboard page.
- On the Clipboard page, press Unpin, then Pin. The line stays at the top.
- Press Clear history and confirm. The pinned line stays. The other lines are gone.
- Press Delete on the pinned line. It is removed.
- Set How many entries back to 50.

**Reset.** Leave the cap at 50.

## M110. Tags and the tag filter

**Preconditions.** M109. At least two ordinary lines are in the history.

**Look for.**

- On the Clipboard page, press Tag on one line. Add two tags, pick a color for each, and save.
- That line shows both tags.
- Choose one tag in the tag menu. Only lines with that tag stay. Choose All tags. The other lines come back.
- Type that tag into Search clipboard and tags. The tagged line stays, and a line without that tag drops out.
- The tags are in `clipboard.json`. They are not in a feed file, not in `desktop/`, and not in a webhook body.

**Reset.** Remove the tags if you do not want to keep them.

## M111. Edit keeps the pin and the tags

**Preconditions.** M110. The tagged line is pinned. Password-like copies is still Skip.

**Look for.**

- Press Edit on that line. Change the text and include a line break. Save.
- The new text is shown. The pin and the tags are still there.
- In Settings, set Password-like copies to Hide for 30 seconds. Copy a made-up password-like line.
- That row says Hidden password. Edit is off, and the text is not shown.
- Set Password-like copies back to Skip.

**Reset.** Leave Password-like copies on Skip. Delete the hidden row if it is still there, or wait 30 seconds.

## M112. Preview shows the full text

**Preconditions.** M111. One saved line has more than one line of text.

**Look for.**

- The list shows that line as one shortened line.
- Click the row. A preview opens with the full text and the line breaks kept. The preview cannot be edited.
- Close the preview.
- A Hidden password row, while one is still on screen, does not open a preview and does not show the text.

**Reset.** None.

## M113. Search the web uses the desktop engine

**Preconditions.** M97. The default browser has a search engine. Use an ordinary line.

**Look for.**

- Search the web is available on that line. Leave it unpressed. No browser window opens.
- Press Search the web. The default browser opens a search for that text, using the browser's own search engine. TetherBot does not name a search site.
- On a Hidden password row, Search the web is off.
- If the browser's engine cannot be read, Search the web stays available and uses the search fallback in Settings. M115 covers that.

**Reset.** Close the browser tab. This check uses an ordinary line.

## M114. The tag filter does not freeze

**Preconditions.** Log out and back in after this version is installed, then open the TetherBot window. M110. At least one ordinary line has a tag.

**Look for.**

- On the Clipboard page, open the tag menu and choose that tag.
- The window stays responsive. The list shows the tagged line.
- Choose All tags. The other lines come back.
- Type in Search clipboard and tags. The list updates, and the window still responds.

**Reset.** Choose All tags and clear the search.

## M115. Search the web follows Chrome, or the Settings fallback

**Preconditions.** M113. The default browser is Chrome or Chromium, with a normal profile. Search fallback in Settings still shows the DuckDuckGo address.

**Look for.**

- On an ordinary line, Search the web is available. Leave it unpressed. No browser opens.
- Press Search the web. Chrome opens a search for that text with Chrome's own search engine.
- The copied text is not in the bridge log, a feed file, or a webhook body.
- In Settings, change Search fallback to `https://example.test/find?q={searchTerms}` only if you need to confirm the fallback. With the browser engine readable, Search the web still uses Chrome.
- If a profile has no readable engine, the button stays available, its tooltip says it uses the search fallback from Settings, and a press opens that address. Change the address back to the DuckDuckGo default when finished.

**Reset.** Leave Search fallback on the DuckDuckGo address. Close the browser tab.

## M116. A hidden password can be pinned, not tagged

**Preconditions.** M107. Password-like copies is Hide for 30 seconds. One Hidden password row is on the Clipboard page.

**Look for.**

- Tag, Edit, and Search the web are off. Preview does not open.
- Pin is available. Pin the row. It stays at the top.
- Wait 30 seconds. The row disappears, including from the clipboard menu.
- That text is not in `clipboard.json`.
- Set Password-like copies back to Skip.

**Reset.** Leave Password-like copies on Skip.

## M117. Settings opens and the search fallback hint is visible

**Preconditions.** This version is installed. Close Settings if it is already open. M115 can stay as it is. Password-like copies and the search address are unchanged.

**Look for.**

- Open Settings from the TetherBot menu. The window opens. No error dialog appears.
- The Clipboard section has a Search fallback row. Its second line says the address is used when the browser engine cannot be read, the default is DuckDuckGo, and nothing opens until Search the web is pressed.
- The Search address row under it still shows the saved address. Hovering that row shows the same hint.
- Close Settings. The Clipboard page is unchanged.

**Reset.** None.

## M118. Clipboard rows stay one line

**Preconditions.** M112. The window process was started after this version was installed. At least one ordinary line is long enough to fill the text column. One line has a tag. One Hidden password row is on the page, or set Password-like copies to Hide for 30 seconds and copy a made-up password-like line.

**Look for.**

- Each entry is one row. The text is one line and ends with … when it does not fit. It does not wrap under the icons.
- The icons sit in columns, in this order: Edit, Pin, Tag, Copy, Search the web, Delete. Each icon has a tooltip with that name. Search the web may instead say it uses the search fallback from Settings, or that no default search engine is set.
- A thin faint line separates each icon column. The columns line up from row to row.
- A tag is a small colored dot in the text area, not a second line of text. The icon columns do not move when a row has a tag.
- Pin is the ordinary foreground color. After pinning, that pin uses the accent color. Unpinning returns it to the ordinary color. The row stays one line either way.
- On a Hidden password row, Edit, Tag, and Search the web are dimmed and stay in place. Pin, Copy, and Delete stay available. The columns do not shift. The row does not show the hidden text.
- Click the text of an ordinary row. Preview still shows the full text, with line breaks kept.
- Press Search the web on an ordinary row only when you mean to. Nothing opens until that press.

**Reset.** Set Password-like copies back to Skip. Delete the hidden row if it is still there, or wait 30 seconds.

## M119. The clipboard menu rows stay one line

**Preconditions.** Log out and back in after this version is installed, then open the clipboard menu. M118. One pinned line, one tagged line, and one ordinary line are in the history. A Hidden password row is present, or repeat the Hide for 30 seconds step from M118.

**Look for.**

- Each menu row is one line. Pinning and unpinning does not wrap the row onto a second line.
- The same icon columns are there, with the same tooltips and faint separators. Tag dots sit in the text area.
- An unpinned pin is the ordinary foreground color, not faded. A pinned pin uses the accent color.
- On a Hidden password row, Edit, Tag, and Search the web are dimmed and the columns do not shift. The row says Hidden password.
- Pressing an icon does not also copy the line.
- Copy puts that line back on the clipboard.
- Delete removes that row, including a pinned one.
- Edit, Tag, and Search the web open the Clipboard page. They do not open a browser. Search the web on the page is unchanged: nothing opens until that page's button is pressed.

**Reset.** Set Password-like copies back to Skip. Leave the history as you want it.

## M120. A copied screenshot is kept

**Preconditions.** Log out and back in after this version is installed, so the extension and the schema load. Remember copied text is on. Keep copied images is on.

**Look for.**

- Take a screenshot to the clipboard (Print Screen, then copy).
- A thumbnail appears in the clipboard menu and on the Clipboard page. The label names the type and the size, for example Image · PNG · 1.2 MB.
- The file is in `clipboard-images`, next to `clipboard.json` in the TetherBot state directory. `stat -c %a` on that file prints `600`. The directory is `700`.
- `clipboard.json` has `kind` and `mime` for that entry. It does not contain the image bytes or the path `clipboard-images`.

**Reset.** Delete the image if you do not want to keep it.

## M121. Image rows stay one line

**Preconditions.** M120. The window process was started after this version was installed.

**Look for.**

- The image row is one line in the menu and on the page. The label ends with … when it does not fit. It does not wrap under the icons.
- The icons sit in the same columns: Edit, Pin, Tag, Copy, Search the web, Delete. A thin line separates each column. The columns line up with a text row.
- Edit and Search the web are dimmed and stay in place. The Edit tooltip says images are not edited. The Search tooltip says images are not searched.
- Pin, Tag, Copy, and Delete stay available.

**Reset.** None.

## M122. Preview and Copy

**Preconditions.** M120.

**Look for.**

- Click the image row on the Clipboard page. Preview shows the full image, scaled to fit. There is no text editor.
- Copy, then paste into an image editor or a chat. The paste is the image, with its original type.
- No second row appears for that same image.
- Clicking the row in the panel menu copies the image back, the same way clicking a text row copies the text. It does not type into the focused window.

**Reset.** None.

## M123. Pin and Tag an image

**Preconditions.** M120.

**Look for.**

- Pin the image. It sorts first. Clear leaves it in place. It also stays when the history is past the item limit.
- Add a tag. The colored dot shows in the row. Choosing that tag in the filter shows the image and hides untagged rows.

**Reset.** Unpin, or delete the image, when you are done. Clear does not remove a pinned image.

## M124. Delete and Clear remove files

**Preconditions.** M120. One image is pinned and one image is not.

**Look for.**

- Delete one image. Its file, and its thumbnail if one was written, is gone from `clipboard-images`.
- Clear history. The unpinned image file is gone. The pinned image file is still there until you delete that row.

**Reset.** Leave the history as you want it.

## M125. Rules still apply

**Preconditions.** M120. Keep copied images is on. A password manager from the exclude list is available.

**Look for.**

- Copy an image while that password manager is focused. The image is not kept.
- Turn Keep copied images off. Copy an image from an ordinary app. It is not kept. Copy a line of ordinary text. The text is kept. Images already in the history stay.
- `tetherbotctl clipboard-debug` prints the MIME types and a reason such as `excluded app` or `images-off`. It prints no bytes and no path.

**Reset.** Turn Keep copied images back on.

## M126. Size cap and privacy

**Preconditions.** M120. Keep copied images is on.

**Look for.**

- An image over 10 MiB is not kept. `tetherbotctl clipboard-debug` prints `image-too-large`. It prints no bytes and no path.
- Nothing about the image appears in the feed repository, in `journalctl --user -u tetherbot`, or in a webhook body.

**Reset.** None.

## When you are finished

```bash
systemctl --user disable --now tetherbot
scripts/uninstall.sh --purge
```

That removes the app, launchers, unit, D-Bus file, extension, config, state, and clones. It does not delete keyring items. There is no command in this release that deletes those items.

# Manual checks (v0.1)

Run these on one Fedora 44 desktop with GNOME Shell 50 on Wayland, after you can log in as a normal user. The project is unofficial and not affiliated with xAI.

**Out of scope here:** M9 (webhook-only popup copy), M15 and M16 (a legacy todo sink outside this repository), and M17 (the full uninstall acceptance check). Uninstall is still documented in [SETUP.md](SETUP.md) and is the reset for M1. Do not treat those four as part of this runbook.

Examples use the bot id `primary`. Yours can be any lowercase id of letters, digits, and hyphens. Use the same id in the bot's feed file, in `config.toml`, and in the commands below.

Nothing in these steps belongs in a chat, in `config.toml`, or in this repository: not the webhook URL, not the webhook key, and not the GitHub token. The only place you paste them is the hidden prompt from `tetherbotctl secret set`.

## Suggested order

M1, M2, then the extension install in M14 (log out and back in once), then M3. Do M10 before M4 if the popup has no ask yet. Then M4, M5, M11, M6, M7, M8, M12, M13.

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

**Preconditions.** M3's real routine is in use again (M6's reset is done). Webhook sender is enabled. The key dialog is not built yet: `RequestSecretEntry` returns false. Re-paste means `tetherbotctl secret set`, not a graphical dialog.

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
- Commit a new item, or set `"notify": true` on a new item, in `feed/<bot>.json` and push it with your own git (not by putting the token in the remote). Within one poll, one notification appears. **Approve**, **Veto**, **Snooze**, and **Open chat** work when the item lists those actions. Snooze stays on this machine. Open chat launches Grok Bot when a desktop entry exists. The deep link to one chat is still **TBD, verify**.

**Reset.** Leave the repository configured if you are going on to M11. To stop polling, `tetherbotctl disable repo`.

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

## When you are finished

```bash
systemctl --user disable --now tetherbot
scripts/uninstall.sh --purge
```

That removes the app, launchers, unit, D-Bus file, extension, config, state, and clones. It does not delete keyring items. There is no command in this release that deletes those items.

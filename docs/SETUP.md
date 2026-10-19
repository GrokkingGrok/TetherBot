# Setup

Target machine: Fedora 44, GNOME Shell 50, Wayland, Python 3.13+. Other distributions with the same shell and Python can work. The checks below say so when they only warn.

`scripts/install.sh` installs the bridge for your user. After `systemctl --user enable --now tetherbot` (or `scripts/install.sh --enable`), the bridge exports `io.github.grokkinggrok.TetherBot1` on the session bus. `tetherbotctl` is status, enable, secret set, and webhook test. `tetherbotctl repo setup` is not a command: enabling the repo adapter clones the remote itself. `ssh-deploy-key` is accepted in config and does not run git yet. The step-by-step checks are in [MANUAL-CHECKS.md](MANUAL-CHECKS.md).

## What you need

1. Install Grok Bot and sign in. Decide which bot receives desktop actions (usually the main one). In these docs that bot is called `primary`. Use your own bot id, lowercase, in config.
2. Clone this repository and run `scripts/install.sh`. The installer copies the app, the launchers (`tetherbot`, `tetherbotctl`, `git-credential-tetherbot`), the user unit, and the D-Bus activation file. It enables nothing that touches the network unless you pass `--enable`, which runs `systemctl --user enable --now tetherbot.service`.
3. Paste [prompts/bot-setup.md](prompts/bot-setup.md) into that bot's chat. It asks the bot to create a routine named "Desktop actions" with a webhook trigger.
4. Open that routine on the desktop (bot name, Details, Routines, the routine). In **Webhook**, copy **POST to** and **key**. Store both with `tetherbotctl secret set <bot>-actions`, or with "Set up keys..." in the extension preferences once that button exists. Paste them into that prompt, not into a chat and not into `config.toml`.
5. Optional, for bot-to-desktop updates: create a private repository from `template-repo/`. Put its plain `https://github.com/...` URL in `config.toml` under `[adapters.github-poller]`. Do not put a token in the URL. Create a fine-grained token for that one repository (Contents read and write, Metadata read, about 90 days). Store it with `tetherbotctl secret set github-token`, pasting into the hidden prompt. Set `auth = "https-token"`. The bot writes `feed/<bot>.json` with `tools/feed_write.py` and a fine-grained token in an environment variable on the bot. See [BOT-WRITER.md](BOT-WRITER.md). That token stays off the desktop. `ssh-deploy-key` is not set up in this release.
6. Enable adapters: `tetherbotctl enable webhook` and, if you configured a repository, `tetherbotctl enable repo`. Then `systemctl --user enable --now tetherbot` if you did not pass `--enable` to the installer. `webhook-sender` posts when that adapter is enabled. `github-poller` clones an `https://github.com` remote with `git-credential-tetherbot` on that clone only, and it also polls a `file://` remote. `ssh-deploy-key` does not run git.
7. Install the extension with `scripts/install-extension.sh` (or `make install-extension`). **Log out and back in** (Wayland reloads shell code that way), then enable UUID `tetherbot@grokkinggrok.github.io`.
8. Check `tetherbotctl status`, then `tetherbotctl webhook test <bot>` only when you mean to spend one bot run.
9. If the webhook key changes, use the re-paste flow. The bridge opens its own dialog. The extension never receives the key.

[prompts/coding-agent-setup.md](prompts/coding-agent-setup.md) is the same work, written for a coding agent on the machine.

## Installer contract

`scripts/install.sh` is Bash with `set -euo pipefail`. It warns, and does not stop, when `python3` is older than 3.13, when PyGObject or the `Secret-1` typelib cannot be imported, when `git` is missing, or when `gnome-shell` is missing or is not version 50. It copies the bridge package to `~/.local/share/tetherbot/app/`, installs the three launchers, copies the unit and the D-Bus service file (with `Exec` rewritten to the launcher), creates `config.toml` from [data/config.example.toml](../data/config.example.toml) only when that file is missing, and reloads the user systemd manager when one is running. It does not enable or start the service unless you pass `--enable`. It never asks for or reads a secret.

`scripts/uninstall.sh` removes the launchers, the app copy, the unit, the D-Bus file, and the extension directory. It is safe to run twice. `--purge` also removes the config directory, the state directory, and `~/.local/share/tetherbot` (including clones), after a prompt, or with `--yes` when there is no terminal. It never deletes secret-service items.

## Where files go

| What | Path |
|---|---|
| Daemon and tools | `~/.local/share/tetherbot/app/` and launchers in `~/.local/bin/`: `tetherbot`, `tetherbotctl`, `git-credential-tetherbot` |
| Config, no secrets | `~/.config/tetherbot/config.toml` |
| State, queue, logs | `~/.local/state/tetherbot/` (`queue/`, `items.json`, `bridge.log`, `backups/`) |
| Repository clones | `~/.local/share/tetherbot/repos/<name>/` |
| User unit | `~/.config/systemd/user/tetherbot.service` |
| D-Bus activation | `~/.local/share/dbus-1/services/io.github.grokkinggrok.TetherBot1.service` |
| Secrets | Desktop secret service only (GNOME Keyring via libsecret) |

`~` here means the installing user's home, resolved through the XDG base directories when those variables are set. The bridge does not hard-code a particular home directory.

## Secrets

- Webhook slots store `{url, key}` under libsecret schema `io.github.grokkinggrok.TetherBot.Secret`, attributes `{kind: "webhook", slot: "<slot>"}`.
- A git token uses `{kind: "github-token", slot: "<slot>"}`.
- The extension preferences window only requests that the bridge open its own dialog (`RequestSecretEntry`). The secret never crosses D-Bus.
- A terminal fallback, `tetherbotctl secret set <slot>`, reads with `getpass` and does not echo.

If the login keyring is locked, affected adapters wait in a degraded state with reason `keyring locked`. They do not prompt and they do not fall back to a plain file. A queued action stays pending until the keyring is unlocked.

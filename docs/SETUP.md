# Setup

Target machine: Fedora 44, GNOME Shell 50, Wayland, Python 3.13+. Other distributions with the same shell and Python can work. The checks below say so when they only warn.

`python -m tetherbot` from a checkout loads config and state, exports the session bus, and waits in a main loop. `python -m tetherbot.ctl` is `tetherbotctl`: status, enable, secret set, and webhook test. The installer still does not place `~/.local/bin/tetherbotctl`, and the unit `ExecStart` is `/bin/false`. `tetherbotctl repo setup` is not implemented. You can run `scripts/install.sh` to copy inactive templates. Wait for the rest of the v0.1 roadmap before pointing a real webhook at this tree.

## What you need

1. Install Grok Bot and sign in. Decide which bot receives desktop actions (usually the main one). In these docs that bot is called `primary`. Use your own bot id, lowercase, in config.
2. Clone this repository and run `scripts/install.sh`. The installer copies files, installs the user unit and the D-Bus activation file, and enables nothing that touches the network. `--enable` is refused while the unit's `ExecStart` is `/bin/false`.
3. Paste [prompts/bot-setup.md](prompts/bot-setup.md) into that bot's chat. It asks the bot to create a routine named "Desktop actions" with a webhook trigger.
4. Open that routine on the desktop (bot name, Details, Routines, the routine). In **Webhook**, copy **POST to** and **key**. Store both with `tetherbotctl secret set <bot>-actions`, or with "Set up keys..." in the extension preferences once that button exists. Paste them into that prompt, not into a chat and not into `config.toml`.
5. Optional, for bot-to-desktop updates: create a private repository from `template-repo/` once that directory exists. Create a fine-grained token for that one repository (Contents read and write, Metadata read, about 90 days). Store it with `tetherbotctl secret set github-token`. Give the bot write access to the same repository through whatever Grok Bot already supports for git hosting. The recommended credential shape is **TBD, verify** (roadmap).
6. Enable adapters: `tetherbotctl enable webhook` and, if you configured a repository, `tetherbotctl enable repo`. `webhook-sender` posts once the bridge process is actually running. `github-poller` starts with that process and, in v0.1, runs git only for a `file://` remote. `https-token` and `ssh-deploy-key` wait for the credential helper, so enabling the repo adapter does not contact GitHub yet. The unit's `ExecStart` is still `/bin/false`. `systemctl --user enable --now tetherbot` only works after the installer points the unit at the bridge.
7. Install the extension, **log out and back in** (Wayland reloads shell code that way), then enable UUID `tetherbot@grokkinggrok.github.io`.
8. Check `tetherbotctl status`, then `tetherbotctl webhook test <bot>` only when you mean to spend one bot run.
9. If the webhook key changes, use the re-paste flow. The bridge opens its own dialog. The extension never receives the key.

[prompts/coding-agent-setup.md](prompts/coding-agent-setup.md) is the same work, written for a coding agent on the machine.

## Installer contract

`scripts/install.sh` is Bash with `set -euo pipefail`. It warns, and does not stop, when `python3` is older than 3.13, when PyGObject or the `Secret-1` typelib cannot be imported, when `git` is missing, or when `gnome-shell` is missing or is not version 50. The scaffold only copies templates, so those checks are not fatal yet. It copies the unit and the D-Bus service file, creates `config.toml` from [data/config.example.toml](../data/config.example.toml) only when that file is missing, and reloads the user systemd manager when one is running. It does not enable or start the service. It never asks for or reads a secret.

`scripts/uninstall.sh` removes the unit, the D-Bus file, and the app copy. It is safe to run twice. `--purge` also removes the config and state directories, after a prompt, or with `--yes` when there is no terminal. It never deletes secret-service items.

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

If the keyring is locked, affected adapters wait in a degraded state. They do not fall back to a plain file.

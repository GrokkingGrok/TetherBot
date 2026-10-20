# Privacy

Draft for the desktop bridge. TetherBot is unofficial and not affiliated with xAI. This note describes the session as it works today. It does not name a person, a machine, or a repository.

## Session bus

The bridge, the Shell extension, the prefs window, and the TetherBot window talk on the user session bus. The name is `io.github.grokkinggrok.TetherBot1`. Anything else in that same user session can call the interface. A process outside the session cannot.

The extension, the prefs window, and the TetherBot window make no network calls. They do not hold a webhook key, a webhook URL, or a GitHub token. Those values are not placed in D-Bus messages, gsettings, config files, logs, the queue, or the shell process.

## What leaves the machine

Nothing leaves until an adapter is enabled by name.

**Feed repository.** When `github-poller` is enabled, the bridge reads a private Git repository the user configured. That read is `git` talking to the host in the remote URL (`github.com` for an `https://github.com` remote, or a `file://` path that never leaves the machine). The bridge also pushes the files it owns under `desktop/`, including `desktop/state.json`. It does not push `feed/`. The GitHub token, when one is stored, is sent only to that host through the credential helper.

**Webhook.** When `webhook-sender` is enabled, a click that sends an action becomes an HTTPS POST to the webhook URL stored for that bot. The key is the `Authorization: Bearer` header. It is not a field in the body. The body is JSON:

- `schema` (`tetherbot/1`)
- `type` (`actions` or `ping`)
- `batch_id`
- `sent_at`
- `client.name`, `client.version`, and `client.host` (the label `desktop`, not the machine's hostname)
- `actions[]`, each with `action_id`, `item`, `action`, `args`, `created`, and optional `title` and `kind`

`args` is empty except for a `note`, which carries the text the user typed. A ping is `schema`, `type`, and the same `sent_at` and `client` fields. A ping is sent only when the user asks for a test.

No other host is used. There is no telemetry, no analytics, and no crash upload.

## Secrets

Webhook URL, webhook key, and GitHub token live in the desktop secret service (the login keyring), inside the bridge process. The libsecret schema is `io.github.grokkinggrok.TetherBot.Secret`. The prefs window can ask the bridge to open a key dialog. The dialog writes the secret service and does not show a value that is already stored. gsettings holds only UI choices: poll interval, undo length, which bots notify, and which bots are hidden.

## What stays on the machine

The bridge keeps an item cache, the action queue, logs, `timer.json`, and `item-time.json` under the XDG state directory. A local clone of the feed repository, including `desktop/state.json`, stays on the machine except for the push described above. Snooze times stay on this machine. The stopwatch is not written to the feed and is not sent to the bot.

gsettings on this machine stores the poll interval, the undo length, the list of muted bots, and the list of hidden bots.

## Nothing is paid, sent, or deleted from the desktop

The desktop does not charge money, does not sell data, and does not delete items from the bot or from the feed repository. Checking an item off sends the webhook post described above and records the close in the bridge's own `desktop/state.json`. It does not remove the bot's feed file. A webhook post can start a bot run, which uses the account's existing usage. TetherBot does not add a charge of its own.

The extension does not read the screen, files outside the bridge, the clipboard, or other apps.

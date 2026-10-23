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
- `actions[]`, each with `action_id`, `item`, `action`, `args`, `created`, optional `title` and `kind`, and, on a done action, optional `note`

`args` is empty except for a `note` action, which carries `args.text` and may include `args.bot`, the owning bot id. A done action may also include `note` beside `args`. That field is the text typed with Done with note, 1 to 500 characters, and it is omitted for plain Done. None of these fields is a secret. A ping is `schema`, `type`, and the same `sent_at` and `client` fields. A ping is sent only when the user asks for a test.

No other host is used. There is no telemetry, no analytics, and no crash upload.

## Secrets

Webhook URL, webhook key, and GitHub token live in the desktop secret service (the login keyring), inside the bridge process. The libsecret schema is `io.github.grokkinggrok.TetherBot.Secret`. The prefs window can ask the bridge to open a key dialog. The dialog writes the secret service and does not show a value that is already stored. gsettings holds only UI choices: poll interval, undo length, completed-todo history, clipboard history (on or off, whether images are kept, how many entries, which apps to skip, and whether a password-like copy is skipped or hidden for 30 seconds), which bots notify, and which bots are hidden. Clipboard text and image bytes are not gsettings values.

## What stays on the machine

The bridge keeps an item cache, the action queue, logs, `timer.json`, `item-time.json`, `clipboard.json`, and `clipboard-images/` under the XDG state directory. `clipboard.json` is mode 0600. It holds clipboard history. Image files sit beside it, each mode 0600, in a directory mode 0700. They are not under `desktop/`, they are not in the feed clone, and they are not pushed. Snooze times stay on this machine. The stopwatch is not written to the feed and is not sent to the bot. Clipboard history, including image bytes, is not written to the feed, a log, a notification, or a webhook, and it is not sent to the bot. Pins, tags, and edited text stay in `clipboard.json`. Search the web is the one clipboard action that can leave the machine, and only after that button is pressed. It asks the desktop browser to open that browser's own search. When that engine cannot be read, it uses the search fallback shown in Settings. The default is DuckDuckGo, and the address can be changed. An image cannot be searched that way.

gsettings on this machine stores the poll interval, the undo length, completed-todo history (on or off, a number, and a unit), clipboard capture (on or off, images on or off, a cap, the app exclude list, the password-like choice, and the search fallback address), the list of muted bots, and the list of hidden bots.

## Nothing is paid, sent, or deleted from the desktop

The desktop does not charge money, does not sell data, and does not delete items from the bot or from the feed repository. Checking an item off sends the webhook post described above and records the close in the bridge's own `desktop/state.json`. It does not remove the bot's feed file. Show done hides a completed todo that is older than the history window. That hide does not delete the feed entry or the local item cache. A webhook post can start a bot run, which uses the account's existing usage. TetherBot does not add a charge of its own.

The extension reads the clipboard so it can keep that local text and image history. A copy is skipped when a clipboard target marks it sensitive, including `x-kde-passwordManagerHint` or a concealed, sensitive, or confidential type, and when the focused window's class is on the exclude list. A password-like line is skipped too. Chrome on Linux does not set a password MIME type, so that rule is what leaves a Chrome password out of the history. Settings can instead keep a password-like line on this machine for 30 seconds. The window and the menu show Hidden password, and the line is deleted when the 30 seconds are over. The same sensitive and excluded-app rules skip an image. Remember copied images can turn new image capture off. Existing images stay until they are deleted or cleared. The extension does not read the screen. It reads an image file only to draw the thumbnail the bridge already stored. Clipboard text and image bytes are not placed in a D-Bus signal, a log, the feed, or a webhook body. `tetherbotctl clipboard-debug` prints MIME types and the skip reason. It does not print the text, the bytes, or a path. The session bus carries an entry only after those skips, and only to the bridge on this machine. A skipped password-like line is not sent on the bus. An image over 10 MiB is not sent. The note that records the MIME types does not include the text or the bytes. Copy puts an image back through `GetClipboardImage`, then drops the bytes. Pin, tag, and edit calls stay on that bus. The extension does not open a browser. A hidden password cannot be edited, previewed, or searched. An image cannot be edited or searched. Preview shows the image file.

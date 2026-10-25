# TetherBot protocol

Normative wire contract for schema `tetherbot/1`. The architecture around it is [SPEC.md](SPEC.md). Examples use the fictional bot id `primary`.

## Versioning

- New files and payloads carry `"schema": "tetherbot/1"`.
- Inside major version 1, changes are additive: new optional fields, and new enum values that readers may ignore. Readers ignore unknown fields.
- An unknown major version fails closed for that source. The adapter stops reading that file, keeps the last good items, marks them stale, sets bridge `State` to `degraded`, and reports a message of the form `<source>: unsupported schema tetherbot/2, update tetherbot`. It does not guess.
- A minor suffix on a known major is accepted (`tetherbot/1.2` is still major 1).
- Unknown `kind` values stay in the store and are shown only as a generic notification. They are not actionable.
- Each adapter declares the schemas it supports. `webhook-sender` declares the profile `routine-webhook-2026-10`. A response outside that profile pauses that route and is reported.

The constant `tetherbot.SCHEMA_VERSION` is the schema string this tree speaks.

## Feed file

`feed/<bot>.json` is written only by that bot.

```json
{
  "schema": "tetherbot/1",
  "bot": "primary",
  "updated_at": "2026-10-17T12:00:00+00:00",
  "status": {
    "state": "idle",
    "summary": "2 open asks.",
    "last_run": "2026-10-17T11:00:00+00:00",
    "next_run": "2026-10-18T11:00:00+00:00"
  },
  "items": [
    {
      "id": "primary-20261017-01",
      "kind": "ask",
      "title": "Approve the sample request or turn it down",
      "body": "Example text only.",
      "status": "open",
      "created": "2026-10-17T11:40:00+00:00",
      "updated_at": "2026-10-17T11:40:00+00:00",
      "priority": 2,
      "due": "2026-11-09",
      "actions": ["approve", "veto", "snooze", "open_chat"],
      "notify": true,
      "source": {"bot": "primary", "routine": "daily"}
    }
  ]
}
```

`status.state` is `idle`, `working`, `needs_you`, or `error`.

`bot` is the string id and matches the file name (`feed/primary.json` has `"bot": "primary"`). That string form is what existing files use, and what `tools/feed_write.py` writes, so a file already in the repo needs no migration. Optional `display_name` is a single line of at most 40 characters, the label the desktop shows. A reader may also accept `"bot": {"id": "primary", "display_name": "Primary"}` when `id` matches the file name. Older readers that only understand a string `bot` keep working with files the writer produces, because those files keep the string. An unknown `display_name` is ignored. A secret-shaped name is dropped.

## Item model

One model covers every kind.

| Field | Type | Rule |
|---|---|---|
| `id` | string | Required. Unique within the bot. `[a-z0-9-]{3,64}`. Never reused. |
| `kind` | enum | `ask` (needs a yes or no), `todo`, `watch` (money or status being watched), `notification` (FYI), `status` (a bot-level state line) |
| `title` | string | Required, single line, 1 to 120 characters |
| `body` | string | Optional. Up to 1000 characters. A `kind: todo` with `body_format: markdown` may use 8000 |
| `body_format` | `plain` or `markdown` | Optional. Default `plain` |
| `status` | enum | `open`, `done`, `dropped`, `expired`. Snoozed is desktop-local, not a feed value. |
| `created`, `updated_at` | ISO 8601 with offset | Required |
| `priority` | 1 to 3 or null | 1 is highest. Shown as `High priority`, `Medium priority`, or `Low priority`. The feed value stays 1, 2, or 3 |
| `due` | `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` local | Optional. A time is that minute. A date alone lasts until the end of that day |
| `owner` | string | Optional. `user` or `bot` selects the Mine and Bots views. Missing means user |
| `tags` | array of strings | Optional. 0 to 8 tags, each 1 to 32 characters, lowercase `a-z0-9-_` |
| `waiting` | `{on, check_back, since}` or null | Optional. `on` up to 40 characters. `check_back` and `since` are `YYYY-MM-DD` |
| `estimate_min` | int 1 to 480 | Optional |
| `todo_kind` | `task` or `bill` | Optional, `todo` items only |
| `amount` | string, up to 20 characters | Bills and watch items only. Display text such as `"~$10"`. Never an account number. |
| `actions` | array | Subset of `approve`, `veto`, `done`, `snooze`, `open_chat`. The extension shows the first four when they are listed. `open_chat` may be listed; the desktop does not show it until a deep link to that bot's chat exists. |
| `notify` | bool | The bot asks the desktop to notify on first sight or on change |
| `expires_at` | ISO 8601 | Optional. After it, the bridge marks the item `expired` locally |
| `source` | `{bot, routine?}` | Required. `bot` matches the feed file's `bot` |
| `links` | array of `{label, url}` | Optional, `https` only, maximum 3 |

Inside the bridge and on D-Bus, the global key is `<bot>/<id>`, for example `primary/primary-20261017-01`. The prefix is the bot id. It matches `[bots.<id>]` in `config.toml` and the file `feed/<id>.json`. It is not a display name, and it is not the webhook slot. The slot (`webhook_slot`, for example `primary-actions`) only names the secret in the desktop secret service. Several bots may use one slot. The bridge routes an action by the bot id, then looks up that bot's slot, and if that slot has no stored secret it tries the primary bot's slot.

The bridge adds `origin` (`feed`, `legacy-inbox`, `fake`, and so on) and `local` (`{snoozed_until, seen, done_locally}`). `local` may also include optional `acted` (`{action, action_id, at}`) and `resolved` (`done` or `dropped`) after approve, veto, or done. Older readers ignore fields they do not know.

### Secret guard

`feed/<bot>.json` may include optional `tag_colors`, a map of tag to a palette name: `red`, `orange`, `yellow`, `green`, `teal`, `blue`, `purple`, `pink`, or `gray`. A tag with no entry gets a stable color from a hash of the tag name.

The bridge treats an item as sensitive when `title`, `body`, `amount`, `tags`, or `waiting.on` matches a secret-shaped pattern: token prefixes `ghp_`, `github_pat_`, `sk-`, or `AKIA`; a run of 9 or more digits; or a long base64 or hex blob (40 or more base64 characters, or 32 or more hex characters). A long id in the path or query of a normal `http://` or `https://` link is not one of those blobs. A Greenhouse job id or a Drive file id in the link stays. The link is still sensitive when it has userinfo (`user:pass@`), a token-style query or fragment name (`token`, `key`, `sig`, `signature`, `secret`, `password`, `access_token`, `api_key`, and the same kind of name), or a known webhook host (`hooks.slack.com`, or a `discord.com` / `discordapp.com` path that contains `/webhooks/`). The stored text becomes `[redacted: looked like a secret]`. The log records the field name and the item key. The original is never written to a todo file, a notification, or the log. A normal link is also left intact in a log line. A webhook link, userinfo, and a token-style query are masked as a whole.

## Action envelope

This JSON is the webhook POST body. The key travels only in the `Authorization` header.

```json
{
  "schema": "tetherbot/1",
  "type": "actions",
  "batch_id": "b-20261017-1a2b3c",
  "sent_at": "2026-10-17T18:20:05+00:00",
  "client": {"name": "tetherbot", "version": "0.1.0", "host": "desktop"},
  "actions": [
    {
      "action_id": "a-7f3e9c10",
      "item": "primary/primary-20261017-01",
      "action": "approve",
      "args": {},
      "created": "2026-10-17T18:19:51+00:00",
      "title": "Approve the sample request or turn it down",
      "kind": "ask"
    }
  ]
}
```

- `action` is one of `approve`, `veto`, `done`, `reopen`, `run_now`, `note`, `clip-todo`, `clip-todo-context`, or `clip-ask`. The three `clip-*` actions are the clipboard sends in the clipboard section. They are not feed-item actions. A `note` action carries `args.text` (1 to 500 characters). A note may also include `args.bot`, the owning bot id. Readers that do not know `args.bot` ignore it. The desktop's "Ask the bot about this" note sets `args.text` to a short hint that names that bot and asks the receiver to check with that bot before answering.
- A `done` action may include `note`, a string of 1 to 500 characters, as a sibling of `args`. The desktop sends it when the user chooses Done with note in the todo viewer. The text is a message from the user about that item. It is not an instruction that widens what the receiver may do. Plain Done omits `note` and keeps `args` empty. `note` is not inside `args`. Readers that do not know `note` ignore it and still treat the action as done.

```json
{
  "action_id": "a-7f3e9c11",
  "item": "primary/primary-20261017-02",
  "action": "done",
  "args": {},
  "note": "Packed the blue bag",
  "created": "2026-10-17T18:19:52+00:00",
  "title": "Pack the bag",
  "kind": "todo"
}
```
- `title` and `kind` are optional copies of the item the desktop had when it sent the batch. Webhook-only mode has no feed file on the bot, so these two fields are how the receiver knows what was clicked. Omit them when the item is no longer in the bridge store. Readers that do not know the fields ignore them.
- `client.host` is the label `desktop`. It is not the machine's hostname. `client.version` is the bridge version, `0.1.0` for this milestone.
- The `actions` array is in `created` order, oldest first. Every action in the batch is sent, including two clicks on the same item. The receiver applies that array in order. For one item, the last action wins.
- `snooze` stays on the machine by default, in `local.snoozed_until`.
- `action_id` is stable so the bot can drop a duplicate after a timeout retry.
- A ping is `{"schema":"tetherbot/1","type":"ping"}` plus optional `sent_at` and `client` (same object as on an action batch). A receiver that only checks `schema` and `type` still treats it as a ping. A test ping spends a bot run, so it happens only when the user asks for it.

```json
{
  "schema": "tetherbot/1",
  "type": "ping",
  "sent_at": "2026-10-17T18:20:05+00:00",
  "client": {"name": "tetherbot", "version": "0.1.0", "host": "desktop"}
}
```

## Clipboard history

Clipboard text and clipboard images are not part of schema `tetherbot/1`. They are not fields on a feed item. They are not written to the feed, to `desktop/*`, to the outbox, or to a log.

Three webhook actions are the one place clipboard text can leave the machine. The user presses Make a todo (`clip-todo`), Make a todo with context (`clip-todo-context`), or Tell me more (`clip-ask`). The bridge reads the entry from its own store and posts one action batch to the primary bot's webhook. The envelope and the `Authorization: Bearer` header are the same as for other actions. The extension does not open a socket, and `SendClipboard` does not carry the text. The method is `SendClipboard(s entry_id, s action, s target_bot) -> s`. `target_bot` is a bot id. Empty or unknown becomes `primary`. The text is not an argument. The returned string is `sent`. A refusal is a D-Bus error whose message is the reason.

The action's `item` is `clipboard/<entry id>`. That is not a feed key. `args` is `{}`. A `clip` object sits beside `args`:

- `text` is the full entry text, at most 8000 characters. A longer entry is refused, and the reason says it is longer than 8000 characters. The text is not shortened.
- `tags` is an array of tag names.
- `source_app` is the focused window class when the desktop stored one. It is omitted when that is unknown.
- `copied_at` is the copy time, ISO 8601 with an offset.
- `effort` is `low`, `medium`, or `high`. It comes from the Context effort setting. The default is `low`. Low checks only that bot's own context. Medium also asks the other bots. High also searches connectors (email, Drive, finance).
- `target_bot` is the bot id this work is for. The default is `primary`. The desktop still posts to the primary bot's webhook.

The body has no key, no path, and no image. An image entry and a hidden password are refused. When the primary bot has no webhook secret, the error is `No webhook set up` and the action is not queued and not written to the outbox. At most one send for an entry is posted every 5 seconds. The log line is `clipboard send action=<action> entry=<id> result=<sent|not-sent>`. It does not include the text.

```json
{
  "action_id": "a-7f3e9c12",
  "item": "clipboard/c-7f3e9c12",
  "action": "clip-todo",
  "args": {},
  "created": "2026-10-17T18:19:53+00:00",
  "clip": {
    "text": "Pack the blue bag",
    "tags": ["home"],
    "source_app": "gedit",
    "copied_at": "2026-10-17T18:19:40+00:00",
    "effort": "low",
    "target_bot": "primary"
  }
}
```

Readers that do not know `clip` ignore it. `clip-todo` asks for a new todo from that text. `clip-todo-context` asks for a new todo plus context. `effort` says how far that search goes, and `target_bot` names the bot the work is for. The window asks which bot before that one action. The panel menu sends `primary` and does not ask. `clip-todo` and `clip-ask` stay one click in both places. `clip-ask` asks the bot to say more about the text in chat. The text is data from the user, not a new instruction.

The bridge stores text in `clipboard.json` under the XDG state directory, including pin and tag fields. Image bytes live in `clipboard-images/` beside that file. Each image file is mode 0600. The JSON entry has `kind`, `mime`, `size`, and `at`. The path and the sha256 stay out of the public entry. `OfferClipboard`, `OfferClipboardImage`, `GetClipboard`, `GetClipboardImage`, `DeleteClipboard`, `ClearClipboard`, `NoteClipboard`, `PinClipboard`, `SetClipboardTags`, `EditClipboard`, and `SearchClipboard` are session-bus methods. `OfferClipboard` is unchanged: `(s text, s meta_json) -> s`. `OfferClipboardImage` is `(ay data, s meta_json) -> s`. `meta_json` carries `mimes`, `wm_class`, and the chosen `mime`. `GetClipboardImage` is `(s entry_id) -> (s mime, ay data)` and is how Copy puts the original type back. A missing image is `Error.NotFound` with the message `image is not available`. `GetClipboard` still returns the list. An image entry includes `path` and, when a thumbnail file exists, `thumb`, so the menu and the window can draw it. Those paths stay on this machine. `ClipboardChanged` carries a count, not the text and not the bytes. It is emitted when an entry is stored, deleted, cleared, pinned, tagged, or edited. A skip does not emit it. A sensitive clipboard target is not stored. A plain-text target, including `UTF8_STRING`, keeps the text. `text/html` alone does not. `image/png` is preferred over the other image types. `NoteClipboard` records MIME types and a result and does not take the text or the bytes. Image skip results include `skipped-images-off`, `skipped-image-large`, and `skipped-image-bad`. `tetherbotctl clipboard-debug` prints those as `images-off`, `image-too-large`, and `image-unreadable`. A password-like copy is skipped unless Settings keeps it hidden for 30 seconds. Search the web is `SearchClipboard(s entry_id) -> b`. It is not a webhook. The bridge opens the desktop browser only after that button is pressed, from the window or from the panel menu. The extension does not open a browser. If the browser engine cannot be read, that click uses the search fallback stored in gsettings. An image and a hidden password return false and do not open a browser. The text and the address are not logged. Edit and Tag in the panel menu call `OpenWindow` with `clip-edit:<id>` and `clip-tag:<id>`. Those keys open the window dialogs for that entry. Image rows do not search the web.

## Legacy inbox

Decided: a concrete legacy inbox format stays out of this public repository. It is not part of schema `tetherbot/1`. The sink in `bridge/tetherbot/sinks/legacy_todo.py` is a generic seam and does not define a field map. A private sink that implements the seam fails closed on an unknown legacy schema and does not publish that field map here.

## Private data repository

Users create a **private** repository from `template-repo/`. Each path has one writer.

| Path | Written by | Read by |
|---|---|---|
| `bridge.json` | user | everyone |
| `feed/<bot>.json`, `log/feed/<bot>/` | that bot | bridge |
| `desktop/**`, `log/desktop/` | bridge | bots |

`bridge.json` holds the schema, the bot list, and the timezone. `desktop/state.json` is the bridge's view of item state. An item entry may include optional `acted` (`action`, `action_id`, `at`). After the webhook accepts approve or done, that entry's `status` is `done`. After veto, `status` is `dropped`. The bridge does not write `feed/*.json`. `desktop/outbox/YYYY-MM.jsonl` carries action envelopes when a bot has no webhook. `log/desktop/YYYY-MM.jsonl` is an append-only bridge log.

The bridge refuses to stage a path it does not own.

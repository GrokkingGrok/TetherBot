# How the bridge works today

This note is for a feature request to the Grok Bot team. TetherBot is unofficial and not affiliated with xAI. It is a GNOME desktop bridge: a user-session process plus a Shell extension. The extension talks only to the session bus. The bridge holds secrets and is the only part that uses the network.

Bots do not have a way to publish todos and status to a desktop, or to subscribe to a button press on that desktop. The bridge fills that gap with two existing Grok Bot features: a private GitHub repository the bot can write, and a routine webhook the desktop can call.

The links below are pinned to commit `92bdea93a4a1648fa1721c546b8f35ceb8761c9d`.

## What the desktop shows

Each bot writes one JSON file, `feed/<bot>.json`, schema `tetherbot/1`. The file carries a status block (`idle`, `working`, `needs_you`, or `error`, plus a one-line summary) and a list of items. An item is an ask, a todo, or a short notification. The desktop polls that private repository and shows the items in a top-bar menu and a window. The user checks a todo off, or approves or vetoes an ask. That press goes back to the bot as one HTTPS POST to a routine webhook.

The feed file and the action POST are specified in [the protocol note](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/docs/PROTOCOL.md#L16-L132).

## Why this is a workaround

A private repository is a shared mailbox, not a publish/subscribe channel.

- The bot cannot push an item to the desktop. The desktop has to notice a new commit. The poll defaults to 120 seconds, so a todo written from a phone shows up on the next poll, not when it was written.
- The desktop cannot subscribe to a bot. Status, asks, and todos all have to be written into that JSON file by a bot-side script.
- A button press cannot be delivered as an event to the bot. It is an HTTP POST that starts a routine run, spends usage, and then the bot is expected to edit the feed file so the desktop can see the result on a later poll.
- The user has to create a private repository, a fine-grained token for the bot, a second token for the desktop, and a webhook key. All of that exists only because there is no first-party path from a bot to the desktop.

The poller that reads the repository is [`GitHubPoller`](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/bridge/tetherbot/adapters/github_poller.py#L173-L238). The webhook POST is [`WebhookSender.send`](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/bridge/tetherbot/adapters/webhook_sender.py#L72-L112) and [`post_json`](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/bridge/tetherbot/adapters/webhook_sender.py#L473-L500). Optional sinks, which are off until enabled, implement one small interface: [`Sink`](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/bridge/tetherbot/sinks/base.py#L15-L23). The in-tree example stays generic and does not define an inbox format: [`LegacyTodoSink`](https://github.com/GrokkingGrok/TetherBot/blob/92bdea93a4a1648fa1721c546b8f35ceb8761c9d/bridge/tetherbot/sinks/legacy_todo.py#L16-L27).

## What a native feature would replace

A publish/subscribe path from a bot to the user's own desktops would replace both the private-repository poll and the routine webhook.

The bot would publish the same kind of payload the feed file holds today: status, asks, and todos, schema `tetherbot/1`. The desktop would subscribe and update when the bot publishes, instead of polling git. A button on the desktop would publish an action (`approve`, `veto`, `done`, `reopen`) back to that bot, and the bot would see it as an event rather than as an HTTP request that starts a routine. The desktop would still show only that user's bots, and secrets for any remaining setup would still stay in the desktop secret service.

Until that exists, the repository poll and the routine webhook are the whole path. The `official` adapter in this tree is the seam where a native channel would plug in, without changing the Shell extension.

## Desktop actions routine

Other installs paste [prompts/bot-setup.md](prompts/bot-setup.md) into the bot that should receive desktop actions. That prompt creates a routine named "Desktop actions". A note about another bot's item includes that bot's id in `args.bot` and a short hint in `args.text`. The routine checks with that bot before answering, and it does not treat the note as new instructions.

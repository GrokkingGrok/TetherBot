# TetherBot data repository

Copy this directory into a **private** git repository. TetherBot and your bots
share the clone. Each path has one writer, so the two sides do not edit the
same file.

This template is an example. The bot id `primary` is a placeholder. Rename
`feed/primary.json` and `log/feed/primary/` to your own bot id (lowercase
letters, digits, and hyphens) before the bot writes it, or leave `primary`
in place. Another bot is a second file, `feed/<id>.json`, with `"bot"` set
to that same id. Copying `feed/primary.json` and changing the id is enough.
The existing primary file does not need a migration. Do not put tokens,
webhook keys, or passwords in any file here. Optional `display_name` is the
label the desktop shows.

The field rules are in `docs/PROTOCOL.md` in the TetherBot repository. The
schema string is `tetherbot/1`.

## Who writes what

| Path | Written by | Read by |
|---|---|---|
| `bridge.json` | you | the bridge and the bots |
| `feed/<bot>.json` | that bot | the bridge |
| `log/feed/<bot>/` | that bot | the bridge |
| `desktop/` | the bridge | the bots |
| `log/desktop/` | the bridge | the bots |

`bridge.json` names the schema, the bots, and a timezone. `feed/<bot>.json` is
that bot's status and items. `desktop/state.json` is the bridge's view of
item state. After Approve, Veto, or Done, an item entry may include optional
`acted` (`action`, `action_id`, `at`). Once the webhook accepts, `status` in
that entry is `done` for approve and done, and `dropped` for veto. The bridge
does not edit `feed/`. `desktop/outbox/` is reserved for a later release.
`log/desktop/` is an append-only bridge log.

The bridge refuses to stage a path it does not own. It owns `desktop/` and
`log/desktop/` only.

## Remote URL

Use a plain `https://github.com/OWNER/REPOSITORY.git` URL in
`config.toml`. Do not put a token in the URL. Store a fine-grained token
with `tetherbotctl secret set github-token`. The bridge supplies that token
through `git-credential-tetherbot` on this clone only.

`ssh-deploy-key` is not set up in this release.

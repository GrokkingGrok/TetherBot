# Bot-side feed writer

`tools/feed_write.py` is a standalone Python 3.10+ script. It edits `feed/<bot>.json` in the private data repository through the GitHub REST contents API. The desktop bridge keeps polling that file. This script does not import the bridge, and it never reads or writes `desktop/*`.

The token is a fine-grained personal access token scoped to that one repository. Permissions are Contents read and write, plus Metadata read, and nothing else. Keep it in an environment variable on the bot (default `TETHERBOT_FEED_TOKEN`). Do not put it on the desktop, in this repository, in a URL, or in a log. Fine-grained tokens expire (maximum 1 year). Set a renewal reminder. An expired or rejected token exits with a one-line error so the bot can report it.

Examples use the fictional bot id `primary` and a placeholder `owner/name`.

## Usage

```bash
export TETHERBOT_FEED_TOKEN   # set in the bot environment, not on the command line
python3 tools/feed_write.py --repo owner/name --bot primary \
  add-todo --title "Send the note" --body "Example text only." --due 2026-10-18

python3 tools/feed_write.py --repo owner/name --bot primary \
  add-ask --title "Approve the sample request or turn it down"

python3 tools/feed_write.py --repo owner/name --bot primary \
  close --key primary/primary-20261017-01

python3 tools/feed_write.py --repo owner/name --bot primary \
  close --key primary-20261017-01 --status dropped

python3 tools/feed_write.py --repo owner/name --bot primary \
  reopen --key primary/primary-20261017-01

python3 tools/feed_write.py --repo owner/name --bot primary \
  status --state idle --summary "3 open todos." \
  --last-run 2026-10-17T12:00:00+00:00 \
  --next-run 2026-10-18T12:00:00+00:00

python3 tools/feed_write.py --repo owner/name --bot primary list --open

python3 tools/feed_write.py --repo owner/name --bot primary --dry-run \
  add-todo --title "Send the note"
```

`--repo` may also come from `TETHERBOT_FEED_REPO`. `--bot` defaults to `primary` (`TETHERBOT_FEED_BOT` overrides that default). `--token-env` names the variable that holds the token.

`add-todo` writes `kind: todo`, `status: open`, and `actions: ["done"]`. `--todo-kind` is `task` or `bill`. `--due` accepts `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, or an ISO 8601 timestamp, and is stored in the protocol form. Omit `--key` and the id is `<bot>-YYYYMMDD-NN`. `add-ask` writes `actions: ["approve", "veto"]`.

Adding a todo or ask whose title and body match an existing open item of the same kind prints that item and does not create a second one. A closed item with the same title is not a match.

`close` defaults to `done`. `close` and `reopen` leave the file alone when the item is already in the requested status. Every real write bumps that item's `updated_at` and the file's `updated_at`. `status` bumps the file timestamp and does not rewrite each item. `--last-run` and `--next-run` are kept when omitted.

`--dry-run` prints the file that would be committed and does not call PUT. `list` prints items as JSON, including `key` as `<bot>/<id>`. That key is not stored in the file.

A write uses the file sha. On HTTP 409 or 422 the script refetches, reapplies the same change to the fresh file, and retries up to 3 times (4 attempts in total).

The desktop popup shows a todo's title, the bot id, the due date when the item has one, and Done when that bot has an outbound route and the item lists `done`. The bot row shows `status.summary` when this command sets it, so a daily run should pass `--summary` (for example `3 open todos.`). The row then stays that sentence while the N todos are in the file. If the status block has no summary, the desktop counts visible open items instead (`1 todo`, `2 todos`) and does not use an item title.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The change was committed, it was already done, or `--dry-run` printed the file |
| 1 | Usage or validation, including secret-shaped title, body, or summary. Nothing is written |
| 2 | GitHub rejected the token (HTTP 401 or 403), including an expired token |
| 3 | The item, feed file, or repository was not found |
| 4 | The file sha was still conflicting after 3 retries |
| 5 | Another HTTP or network failure |

Auth failure is one line on stderr, for example: `feed write failed: GitHub rejected the token (HTTP 401). It may be expired or lack Contents access.` The token is not included.

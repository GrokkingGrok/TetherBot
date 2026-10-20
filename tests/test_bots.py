# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-bot summary, last seen, and state come from the feed status block."""

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from tests.helpers import NOW, make_item
from tests.test_github_poller import _seed, _start
from tetherbot.daemon import BridgeDaemon
from tetherbot.secrets import MemoryBackend, SecretStore
from tetherbot.store import FeedView, ItemStore, parse_feed_view

_CONFIG = """\
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[adapters.webhook-sender]
enabled = true

[bots.primary]
webhook_slot = "primary-actions"
"""

_TITLE = "Approve the sample request or turn it down"


def _boot(tmp_path: Path) -> tuple[BridgeDaemon, list]:
    (tmp_path / "config.toml").write_text(_CONFIG, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        clock=lambda: NOW,
        secrets=SecretStore(MemoryBackend()),
    )
    daemon.start()
    assert daemon.api is not None and daemon.store is not None
    seen: list = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    return daemon, seen


def _rows(daemon: BridgeDaemon) -> list[dict]:
    assert daemon.api is not None
    return json.loads(daemon.api.properties()["Bots"])


def _bots_signals(seen: list) -> list:
    return [
        item
        for item in seen
        if item[0] == "PropertiesChanged" and "Bots" in item[1][0]
    ]


def test_summary_and_last_seen_come_from_the_feed(tmp_path: Path):
    daemon, seen = _boot(tmp_path)
    assert daemon.state == "ok"
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed/primary.json",
        [
            make_item(
                title=_TITLE,
                updated_at="2026-10-17T13:00:00+00:00",
                actions=["approve", "veto"],
                origin="feed/primary.json",
            )
        ],
        now=NOW,
    )
    view = parse_feed_view(
        {
            "updated_at": "2026-10-17T12:00:00+00:00",
            "status": {
                "state": "needs_you",
                "summary": "1 open ask.",
                "last_run": "2026-10-17T12:30:00+00:00",
                "next_run": "2026-10-18T11:00:00+00:00",
            },
        }
    )
    assert view.summary == "1 open ask."
    assert daemon.store.set_feed("primary", view)
    daemon.api.note_bots()
    row = _rows(daemon)[0]
    assert row["summary"] == "1 open ask."
    assert _TITLE not in row["summary"]
    assert row["last_seen"] == int(datetime(2026, 10, 17, 12, 30, tzinfo=UTC).timestamp())
    assert row["last_seen"] != int(datetime(2026, 10, 17, 13, 0, tzinfo=UTC).timestamp())
    assert row["state"] == "needs_you"
    assert row["next_run"] == int(datetime(2026, 10, 18, 11, 0, tzinfo=UTC).timestamp())
    assert _bots_signals(seen)

    quiet = len(seen)
    daemon.api.note_bots()
    assert len(seen) == quiet

    daemon._assign_base("degraded", "ls-remote failed: network")
    daemon.api.publish_state()
    assert _rows(daemon)[0]["state"] == "degraded"
    assert _rows(daemon)[0]["summary"] == "1 open ask."

    daemon._assign_base("ok", "")
    daemon.api.publish_state()
    assert daemon.store.mark_feed_stale("primary")
    daemon.api.note_bots()
    assert _rows(daemon)[0]["state"] == "degraded"
    assert _rows(daemon)[0]["summary"] == "1 open ask."


def test_fallback_ignores_dropped_and_acted_and_veto_emits(tmp_path: Path):
    daemon, seen = _boot(tmp_path)
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed",
        [
            make_item(title=_TITLE, actions=["approve", "veto"]),
            make_item(
                id="dropped-01",
                title="Old closed title",
                status="dropped",
                actions=["approve"],
            ),
            make_item(
                id="todo-01",
                kind="todo",
                title="Send the note",
                actions=["done"],
            ),
            make_item(
                id="todo-02",
                kind="todo",
                title="Second note",
                actions=["done"],
            ),
        ],
        now=NOW,
    )
    daemon.api.note_bots()
    row = _rows(daemon)[0]
    assert row["summary"] == "1 open ask, 2 todos"
    assert row["last_seen"] == 0
    assert _TITLE not in row["summary"]
    assert "Old closed title" not in row["summary"]

    seen.clear()
    daemon.api.call("PerformAction", ("primary/sample-01", "veto", "{}"))
    row = _rows(daemon)[0]
    assert row["summary"] == "2 todos"
    assert _TITLE not in json.dumps(row)
    assert _bots_signals(seen)

    daemon.store.set_feed(
        "primary",
        FeedView(
            updated_at="2026-10-17T12:00:00+00:00",
            summary="1 open ask.",
            state="idle",
        ),
    )
    daemon.api.note_bots()
    seen.clear()
    daemon.api.call("PerformAction", ("primary/todo-01", "done", "{}"))
    assert _bots_signals(seen)
    assert _rows(daemon)[0]["summary"] == "1 open ask."
    assert _rows(daemon)[0]["open_todos"] == 1
    assert _rows(daemon)[0]["last_seen"] == int(NOW.timestamp())


def test_feed_status_survives_reload_and_drops_a_secret_summary(tmp_path: Path):
    path = tmp_path / "items.json"
    store = ItemStore(path)
    view = FeedView(
        updated_at="2026-10-17T12:00:00+00:00",
        state="working",
        summary="2 todos",
        last_run="2026-10-17T11:00:00+00:00",
        next_run="2026-10-18T11:00:00+00:00",
    )
    assert store.set_feed("primary", view)
    assert ItemStore(path).feed("primary") == view
    secret = parse_feed_view({"status": {"state": "idle", "summary": "ghp_" + ("a" * 36)}})
    assert secret.summary is None
    assert secret.state == "idle"
    unknown = parse_feed_view({"status": {"state": "celebrating", "summary": "Hello"}})
    assert unknown.state is None
    assert unknown.summary == "Hello"


def test_daily_summary_wins_over_todo_titles(tmp_path: Path):
    daemon, _seen = _boot(tmp_path)
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed/primary.json",
        [
            make_item(id="todo-01", kind="todo", title="Send the note", actions=["done"]),
            make_item(id="todo-02", kind="todo", title="Pay the bill", actions=["done"]),
            make_item(id="todo-03", kind="todo", title="Call back", actions=["done"]),
        ],
        now=NOW,
    )
    daemon.store.set_feed(
        "primary",
        FeedView(
            updated_at="2026-10-17T12:00:00+00:00",
            summary="3 open todos.",
            state="idle",
        ),
    )
    daemon.api.note_bots()
    row = _rows(daemon)[0]
    assert row["summary"] == "3 open todos."
    assert row["state"] == "idle"
    assert "Send the note" not in row["summary"]
    assert "Pay the bill" not in row["summary"]
    assert "Call back" not in row["summary"]


def test_poll_emits_bots_from_the_feed_status(tmp_path: Path):
    remote = _seed(tmp_path)
    daemon, _clock = _start(tmp_path, remote)
    assert daemon.api is not None and daemon.store is not None
    seen: list = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    daemon.tick_poller()
    row = _rows(daemon)[0]
    assert row["summary"] == "Example feed."
    assert "Approve the sample" not in row["summary"]
    assert row["state"] == "idle"
    feed_at = int(datetime(2026, 10, 17, 12, 0, tzinfo=UTC).timestamp())
    item_at = int(datetime(2026, 10, 17, 11, 40, tzinfo=UTC).timestamp())
    assert row["last_seen"] == feed_at
    assert row["last_seen"] != item_at
    assert _bots_signals(seen)


def test_display_names_counts_and_config_override(tmp_path: Path):
    daemon, _seen = _boot(tmp_path)
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed/primary.json",
        [
            make_item(
                title=_TITLE,
                actions=["approve", "veto"],
                origin="feed/primary.json",
            )
        ],
        now=NOW,
    )
    daemon.store.replace_origin(
        "feed/notes.json",
        [
            make_item(
                id="note-01",
                bot="notes",
                kind="todo",
                title="Write the note",
                actions=["done"],
                source={"bot": "notes"},
                origin="feed/notes.json",
            )
        ],
        now=NOW,
    )
    published = parse_feed_view(
        {
            "bot": "primary",
            "display_name": "Desk",
            "updated_at": "2026-10-17T12:00:00+00:00",
            "status": {"state": "idle", "summary": "1 open ask."},
        }
    )
    assert published.display_name == "Desk"
    daemon.store.set_feed("primary", published)
    daemon.api.note_bots()
    rows = {row["name"]: row for row in _rows(daemon)}
    assert rows["primary"]["display_name"] == "Desk"
    assert rows["primary"]["open_asks"] == 1
    assert rows["notes"]["display_name"] == "Notes"
    assert rows["notes"]["open_todos"] == 1
    assert rows["notes"]["name"] == "notes"
    items = json.loads(daemon.api.call("GetItems", ('{"kinds":["ask","todo"]}',))[0])
    labels = {row["key"]: row["display_name"] for row in items}
    assert labels["primary/sample-01"] == "Desk"
    assert labels["notes/note-01"] == "Notes"

    reloaded = ItemStore(daemon.store.path)
    assert reloaded.feed("primary") is not None
    assert reloaded.feed("primary").display_name == "Desk"


def test_config_display_name_wins_over_the_feed(tmp_path: Path):
    text = _CONFIG.replace(
        'webhook_slot = "primary-actions"\n',
        'webhook_slot = "primary-actions"\ndisplay_name = "Desk"\n',
    )
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        clock=lambda: NOW,
        secrets=SecretStore(MemoryBackend()),
    )
    daemon.start()
    assert daemon.store is not None and daemon.api is not None
    daemon.store.set_feed(
        "primary",
        parse_feed_view({"bot": "primary", "display_name": "From the feed"}),
    )
    daemon.api.note_bots()
    assert _rows(daemon)[0]["display_name"] == "Desk"
    assert _rows(daemon)[0]["name"] == "primary"

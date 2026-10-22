# SPDX-License-Identifier: GPL-2.0-or-later
"""GetItems filters, GetTags, Undo, and OpenWindow."""

import json
from pathlib import Path

import pytest

from tests.helpers import NOW, make_item
from tests.test_service import _api
from tetherbot.service import ServiceError
from tetherbot.store import FeedView

_CONFIG = """\
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[bots.primary]
webhook_slot = "primary-actions"
"""


def _load(daemon, *items: object) -> None:
    assert daemon.store is not None
    daemon.store.replace_origin("feed", list(items), now=NOW)


def _todo(item_id: str, **overrides: object):
    return make_item(
        id=item_id,
        kind="todo",
        actions=["done"],
        title=overrides.pop("title", item_id),
        **overrides,
    )


def _keys(daemon, filter_json: str = "{}") -> list[str]:
    assert daemon.api is not None
    rows = json.loads(daemon.api.call("GetItems", (filter_json,))[0])
    return [row["key"] for row in rows]


def test_filters_search_views_and_tag_colors(tmp_path: Path):
    daemon, _seen = _api(tmp_path, _CONFIG)
    assert daemon.store is not None and daemon.api is not None
    _load(
        daemon,
        _todo(
            "mine-01",
            title="Pack the bag",
            body="wool socks",
            tags=["home", "errand"],
            priority=1,
            owner="user",
            due="2026-10-17 15:00",
        ),
        _todo(
            "bot-01",
            title="File the note",
            body="nothing about socks",
            tags=["home"],
            owner="bot",
            due="2026-10-16",
            waiting={"on": "reply", "since": "2026-10-17"},
        ),
        _todo("later-01", title="Later", tags=["errand"], due="2026-10-21", priority=3),
    )
    daemon.store.set_feed(
        "primary",
        FeedView(updated_at="2026-10-17T12:00:00+00:00", tag_colors=(("home", "teal"),)),
    )
    assert _keys(daemon, '{"query":"wool"}') == ["primary/mine-01"]
    assert _keys(daemon, '{"query":"@home due:today"}') == ["primary/mine-01"]
    assert _keys(daemon, '{"query":"due:overdue"}') == ["primary/bot-01"]
    assert _keys(daemon, '{"query":"p:1"}') == ["primary/mine-01"]
    assert _keys(daemon, '{"tags":["home","errand"]}') == ["primary/mine-01"]
    assert _keys(daemon, '{"view":"mine"}') == ["primary/mine-01", "primary/later-01"]
    assert _keys(daemon, '{"view":"bots"}') == ["primary/bot-01"]
    assert _keys(daemon, '{"view":"waiting"}') == ["primary/bot-01"]
    assert _keys(daemon, '{"view":"today"}') == ["primary/bot-01", "primary/mine-01"]
    rows = json.loads(daemon.api.call("GetItems", ('{"query":"wool"}',))[0])
    assert rows[0]["chips"]["due"]["label"] == "Due Sat 10/17 15:00"
    assert rows[0]["chips"]["priority"]["label"] == "#1"
    assert rows[0]["chips"]["tags"][0] == {"tag": "home", "label": "@home", "tone": "teal"}
    tags = json.loads(daemon.api.call("GetTags", ())[0])
    assert tags[0]["tag"] == "errand"
    assert {row["tag"]: row["count"] for row in tags} == {"errand": 2, "home": 2}
    home = next(row for row in tags if row["tag"] == "home")
    assert home["color"] == "teal"


def test_closed_items_stay_hidden_unless_include_done_days(tmp_path: Path):
    daemon, _seen = _api(tmp_path, _CONFIG)
    assert daemon.api is not None
    _load(
        daemon,
        _todo("open-01", title="Still open"),
        _todo(
            "new-01",
            title="Closed lately",
            status="done",
            updated_at="2026-10-16T12:00:00+00:00",
        ),
        _todo(
            "old-01",
            title="Closed earlier",
            status="done",
            updated_at="2026-10-01T12:00:00+00:00",
        ),
    )
    assert _keys(daemon) == ["primary/open-01"]
    shown = _keys(daemon, '{"include_done_days":7}')
    assert "primary/open-01" in shown
    assert "primary/new-01" in shown
    assert "primary/old-01" not in shown


def test_done_history_is_todos_inside_the_window(tmp_path: Path):
    daemon, _seen = _api(tmp_path, _CONFIG)
    assert daemon.api is not None
    desktop = _todo("desk-01", title="Closed here", updated_at="2026-10-01T12:00:00+00:00")
    desktop.resolved = "done"
    desktop.acted = {"action": "done", "at": "2026-10-17T11:30:00+00:00"}
    dropped = _todo(
        "drop-01",
        title="Dropped",
        status="dropped",
        updated_at="2026-10-17T11:30:00+00:00",
    )
    vetoed = _todo("veto-01", title="Vetoed", updated_at="2026-10-17T11:00:00+00:00")
    vetoed.resolved = "dropped"
    vetoed.acted = {"action": "veto", "at": "2026-10-17T11:30:00+00:00"}
    _load(
        daemon,
        _todo("open-01", title="Still open"),
        _todo(
            "hour-01",
            title="Closed this hour",
            status="done",
            updated_at="2026-10-17T11:30:00+00:00",
        ),
        _todo(
            "old-01",
            title="Closed earlier today",
            status="done",
            updated_at="2026-10-17T10:00:00+00:00",
        ),
        desktop,
        dropped,
        vetoed,
        make_item(
            id="ask-01",
            kind="ask",
            title="Closed ask",
            status="done",
            updated_at="2026-10-17T11:30:00+00:00",
        ),
    )
    hour = set(_keys(daemon, '{"include_done_seconds":3600}'))
    assert hour == {"primary/desk-01", "primary/hour-01", "primary/open-01"}
    year = set(_keys(daemon, '{"include_done_seconds":31536000}'))
    assert "primary/old-01" in year
    assert "primary/drop-01" not in year
    assert "primary/ask-01" not in year
    both = set(_keys(daemon, '{"include_done_days":0,"include_done_seconds":3600}'))
    assert "primary/hour-01" in both
    assert "primary/old-01" not in both
    with pytest.raises(ServiceError, match="include_done_seconds"):
        _keys(daemon, '{"include_done_seconds":true}')
    with pytest.raises(ServiceError, match="999 years"):
        _keys(daemon, '{"include_done_seconds":31536000001}')


def test_undo_drops_a_queued_done_and_reopens_after_send(tmp_path: Path):
    daemon, _seen = _api(tmp_path, _CONFIG)
    assert daemon.api is not None and daemon.store is not None and daemon.queue is not None
    _load(daemon, _todo("todo-01", title="Send the note"))
    key = "primary/todo-01"
    action_id = daemon.api.call("PerformAction", (key, "done", "{}"))[0]
    assert _keys(daemon) == []
    dropped = json.loads(daemon.api.call("Undo", (key,))[0])
    assert dropped == {"result": "dropped"}
    assert daemon.queue.snapshot() == ()
    assert _keys(daemon) == [key]

    action_id = daemon.api.call("PerformAction", (key, "done", "{}"))[0]
    daemon.queue.mark_attempt("primary", [action_id], now=NOW)
    reopened = json.loads(daemon.api.call("Undo", (key,))[0])
    assert reopened["result"] == "reopen"
    queued = daemon.queue.snapshot()
    assert [row.action for row in queued] == ["reopen"]
    assert _keys(daemon) == [key]


def test_open_window_uses_the_bridge_launcher(tmp_path: Path):
    daemon, _seen = _api(tmp_path, _CONFIG)
    assert daemon.api is not None
    seen: list[str] = []
    daemon.launch_window = lambda item_key: seen.append(item_key) or True
    assert daemon.api.call("OpenWindow", ("primary/todo-01",)) == (True,)
    assert daemon.api.call("OpenWindow", ("",)) == (True,)
    assert daemon.api.call("OpenWindow", ("bots",)) == (True,)
    assert seen == ["primary/todo-01", "", "bots"]

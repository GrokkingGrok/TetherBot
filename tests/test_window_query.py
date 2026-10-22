# SPDX-License-Identifier: GPL-2.0-or-later
"""Window filter JSON and the link allow-list. No GTK."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tetherbot.window_query import (
    bot_detail_line,
    can_mark_done,
    copy_body,
    copy_title,
    copy_todo,
    due_undo_keys,
    format_duration,
    format_elapsed,
    format_last_seen,
    format_next_run,
    format_time_record,
    format_top_bar,
    format_tracked,
    is_read_only,
    list_filter,
    merge_undo_items,
    note_done,
    note_payload,
    note_text,
    open_count_label,
    parse_start_clock,
    parse_tracked_total,
    properties_need_reload,
    safe_http_url,
    source_line,
    timer_item_key,
    undo_fraction,
)


def test_list_filter_matches_the_bridge_shortcuts():
    open_items = list_filter(
        view="today",
        query="@home due:today p:1",
        tags=["errand"],
        sort="priority",
        show_done=False,
    )
    assert open_items == {
        "kinds": ["todo"],
        "view": "today",
        "query": "@home due:today p:1",
        "tags": ["errand"],
        "sort": "priority",
        "status": "open",
    }
    done = list_filter(view="all", query="due:overdue", tags=[], sort="due", show_done=True)
    assert done["include_done_days"] == 7
    assert "status" not in done
    fallback = list_filter(view="nope", query="", tags=[], sort="nope", show_done=False)
    named = list_filter(
        view="all", query="", tags=[], sort="due", show_done=False, bots=["notes", "primary"]
    )
    assert named["bots"] == ["notes", "primary"]
    assert fallback["view"] == "all"
    assert fallback["sort"] == "due"


def test_note_names_the_item_and_stays_short():
    bot, payload = note_payload("notes/sample-01")
    assert bot == "notes"
    body = json.loads(payload)
    assert body["schema"] == "tetherbot/1"
    assert body["type"] == "actions"
    action = body["actions"][0]
    assert action["item"] == "notes/sample-01"
    assert action["action"] == "note"
    assert action["args"]["bot"] == "notes"
    assert action["args"]["text"] == note_text("notes")
    assert "question about notes's item" in action["args"]["text"]
    assert "check with notes for updates before answering" in action["args"]["text"]
    assert 1 <= len(action["args"]["text"]) <= 500
    assert len(note_text("n" * 64)) <= 500
    item = {"title": "Pack the bag", "body": "Hold the date."}
    assert copy_title(item) == "Pack the bag"
    assert copy_body(item) == "Hold the date."
    assert copy_todo(item) == "Pack the bag\n\nHold the date."
    assert copy_todo({"title": "Pack the bag"}) == "Pack the bag"
    assert copy_todo({"body": "Hold the date."}) == "Hold the date."


def test_done_and_source_rules():
    open_item = {
        "key": "primary/a",
        "status": "open",
        "actions": ["done"],
        "source": {"bot": "primary", "routine": "daily"},
        "updated_at": "2026-10-17T11:40:00+00:00",
    }
    assert can_mark_done(open_item, True)
    assert not can_mark_done(open_item, False)
    assert not can_mark_done({**open_item, "status": "done"}, True)
    assert is_read_only({"status": "open", "local": {"acted": {"action_id": "a1"}}})
    pacific = timezone(timedelta(hours=-7))
    assert source_line(open_item, pacific) == "primary · daily · Oct 17, 4:40 AM"
    named = {**open_item, "display_name": "Primary"}
    assert source_line(named, pacific) == "Primary · daily · Oct 17, 4:40 AM"
    assert "2026-10-17T" not in source_line(open_item, pacific)


def test_only_a_bots_property_reloads_the_window():
    assert properties_need_reload(["Bots"])
    assert properties_need_reload("Bots")
    assert properties_need_reload(["QueueLength", "Bots"])
    assert not properties_need_reload(["LastSync"])
    assert not properties_need_reload(["QueueLength", "Counts"])
    assert not properties_need_reload(None)
    assert not properties_need_reload({"Bots": "{}"})


def test_bot_detail_line_includes_the_summary():
    now = 1_700_000_000
    detail = bot_detail_line(
        {
            "summary": "Needs a look",
            "last_seen": now - 240,
            "next_run": now + 3600,
            "open_todos": 1,
        },
        now,
    )
    assert detail == "Needs a look · last seen 4 m ago · next run in 1 h · 1 open todo"


def test_bot_list_times_and_counts():
    now = 1_700_000_000
    assert format_last_seen(0, now) == "last seen unknown"
    assert format_last_seen(now - 10, now) == "last seen just now"
    assert format_last_seen(now - 240, now) == "last seen 4 m ago"
    assert format_next_run(0, now) == ""
    assert format_next_run(now + 3600, now) == "next run in 1 h"
    assert open_count_label(1, "todo") == "1 open todo"
    assert open_count_label(3, "ask") == "3 open asks"


def test_tracked_time_uses_the_clock_format():
    assert format_elapsed(42 * 60 + 10) == "42:10"
    assert format_elapsed(3600 + 42 * 60 + 10) == "1:42:10"
    assert format_elapsed(-1) == "--:--"
    assert format_top_bar(0) == "0m"
    assert format_top_bar(5 * 60) == "5m"
    assert format_top_bar(41 * 60 + 20) == "41m"
    assert format_top_bar(3600 + 5 * 60 + 9) == "1:05"
    assert format_top_bar(12 * 3600 + 40 * 60) == "12:40"
    assert format_top_bar(-3) == "--:--"
    assert format_top_bar(True) == "--:--"
    assert format_tracked(90) == "1:30 tracked"
    assert format_tracked(3600 + 42 * 60) == "1:42 tracked"
    assert format_tracked(0) == ""
    assert format_duration(3600 + 42 * 60) == "1:42:00"
    assert format_duration(-30) == "-0:00:30"
    assert format_time_record({"seconds": 90, "kind": "session"}) == "0:01:30"
    assert format_time_record({"seconds": -30, "kind": "adjustment"}) == "-0:00:30 adjustment"
    assert parse_tracked_total("1:42:05") == 3600 + 42 * 60 + 5
    assert parse_tracked_total("1:05") == 3600 + 5 * 60
    assert parse_tracked_total("25m") == 25 * 60
    assert parse_tracked_total("  ") is None
    assert parse_tracked_total("nope") is None
    assert timer_item_key({"state": "running", "item_key": "primary/one"}) == "primary/one"
    assert timer_item_key({"state": "stopped", "item_key": "primary/one"}) == ""
    assert timer_item_key({"state": "idle", "item_key": "primary/one"}) == ""
    assert timer_item_key(None) == ""


def test_parse_start_clock_uses_today_or_yesterday():
    zone = ZoneInfo("UTC")
    now = datetime(2026, 10, 19, 12, 0, tzinfo=zone)
    assert parse_start_clock("11:00", now) == int(
        datetime(2026, 10, 19, 11, 0, tzinfo=zone).timestamp()
    )
    assert parse_start_clock("13:05", now) == int(
        datetime(2026, 10, 18, 13, 5, tzinfo=zone).timestamp()
    )
    assert parse_start_clock("24:00", now) is None
    assert parse_start_clock("9:5", now) is None
    assert parse_start_clock(True, now) is None


def test_safe_http_url_rejects_other_schemes():
    assert safe_http_url("https://example.test/a") == "https://example.test/a"
    assert safe_http_url("  http://example.test/a ") == "http://example.test/a"
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("file:///etc/passwd") is None
    assert safe_http_url("https://example.test/a b") is None
    assert safe_http_url("notes") is None


def test_undo_window_uses_the_configured_length():
    holds = note_done({}, "a", {"key": "a", "title": "A"}, 0, "", 1_000, 10_000)
    assert holds["a"]["until"] == 11_000
    assert undo_fraction(11_000, 6_000, 10_000) == 0.5


def test_cleared_rows_share_one_window_and_leave_together():
    holds = note_done({}, "a", {"key": "a", "title": "A"}, 0, "b", 0)
    holds = note_done(holds, "b", {"key": "b", "title": "B"}, 1, "c", 3_000)
    assert holds["a"]["until"] == holds["b"]["until"] == 8_000
    shown = merge_undo_items([{"key": "c", "title": "C"}], holds, 3_000)
    assert [row["key"] for row in shown] == ["a", "b", "c"]
    assert shown[0]["_undo"]["live"] is True
    assert shown[0]["_undo"]["fraction"] == shown[1]["_undo"]["fraction"] == 1
    assert due_undo_keys(holds, 8_000) == ["a", "b"]
    assert due_undo_keys(holds, 7_999) == []
    holds.pop("a")
    assert due_undo_keys(holds, 8_000) == ["b"]
    assert due_undo_keys(holds, 0, force=True) == ["b"]


def test_a_cleared_row_stays_put_until_its_window_ends():
    items = [
        {"key": "a", "title": "A"},
        {"key": "c", "title": "C"},
    ]
    holds = {
        "b": {
            "key": "b",
            "index": 1,
            "until": 5_000,
            "item": {"key": "b", "title": "B"},
        }
    }
    shown = merge_undo_items(items, holds, 0)
    assert [row["key"] for row in shown] == ["a", "b", "c"]
    assert shown[1]["_undo"]["fraction"] == 1
    later = merge_undo_items(
        [{"key": "c", "title": "C"}],
        {
            "a": {
                "key": "a",
                "index": 0,
                "after": "b",
                "until": 1_000,
                "item": {"key": "a", "title": "A"},
            },
            "b": {
                "key": "b",
                "index": 1,
                "after": "c",
                "until": 5_000,
                "item": {"key": "b", "title": "B"},
            },
        },
        1_000,
    )
    assert [row["key"] for row in later] == ["b", "c"]
    assert later[0]["_undo"]["fraction"] == 0.8
    pinned = merge_undo_items(
        [{"key": "c", "title": "C"}],
        {"a": {"key": "a", "index": 0, "until": 0, "item": {"key": "a", "title": "A"}}},
        0,
        pin_expired=True,
    )
    assert [row["key"] for row in pinned] == ["a", "c"]
    assert pinned[0]["_undo"]["fraction"] == 0
    assert pinned[0]["_undo"]["live"] is False
    assert undo_fraction(5_000, 4_000) == 0.2

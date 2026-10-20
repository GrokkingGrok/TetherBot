# SPDX-License-Identifier: GPL-2.0-or-later
"""Window filter JSON and the link allow-list. No GTK."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from tetherbot.window_query import (
    ASK_TEXT,
    can_mark_done,
    format_elapsed,
    format_top_bar,
    format_tracked,
    is_read_only,
    list_filter,
    note_payload,
    parse_start_clock,
    safe_http_url,
    source_line,
    timer_item_key,
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
    assert fallback["view"] == "all"
    assert fallback["sort"] == "due"


def test_note_names_the_item_and_stays_short():
    bot, payload = note_payload("primary/sample-01")
    assert bot == "primary"
    body = json.loads(payload)
    assert body["schema"] == "tetherbot/1"
    assert body["type"] == "actions"
    action = body["actions"][0]
    assert action["item"] == "primary/sample-01"
    assert action["action"] == "note"
    assert action["args"]["text"] == ASK_TEXT
    assert 1 <= len(ASK_TEXT) <= 500


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
    assert source_line(open_item) == "primary · daily · 2026-10-17T11:40:00+00:00"


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

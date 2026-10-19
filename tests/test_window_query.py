# SPDX-License-Identifier: GPL-2.0-or-later
"""Window filter JSON and the link allow-list. No GTK."""

import json

from tetherbot.window_query import (
    ASK_TEXT,
    can_mark_done,
    is_read_only,
    list_filter,
    note_payload,
    safe_http_url,
    source_line,
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


def test_safe_http_url_rejects_other_schemes():
    assert safe_http_url("https://example.test/a") == "https://example.test/a"
    assert safe_http_url("  http://example.test/a ") == "http://example.test/a"
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("file:///etc/passwd") is None
    assert safe_http_url("https://example.test/a b") is None
    assert safe_http_url("notes") is None

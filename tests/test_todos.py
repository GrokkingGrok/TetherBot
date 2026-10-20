# SPDX-License-Identifier: GPL-2.0-or-later
"""Schema additions, search shortcuts, and tag colors."""

from datetime import UTC, timedelta, timezone

import pytest

from tests.helpers import NOW, make_item
from tetherbot.model import Item
from tetherbot.todos import created_label, due_label, due_tone, parse_query, tag_color

ZONE = NOW.tzinfo
assert ZONE is not None


def test_markdown_todo_body_can_hold_8000_characters():
    item = make_item(
        kind="todo",
        body_format="markdown",
        body=("Note. " * 2000)[:8000],
        actions=["done"],
    )
    assert item.body_format == "markdown"
    assert len(item.body) == 8000
    assert item.redacted_fields == ()
    with pytest.raises(ValueError, match="8000"):
        make_item(kind="todo", body_format="markdown", body="x" * 8001, actions=["done"])


def test_plain_body_stays_at_1000_and_tags_are_guarded():
    with pytest.raises(ValueError, match="1000"):
        make_item(kind="todo", body="y" * 1001, actions=["done"])
    secret = "abcdef0123456789abcdef0123456789"
    item = make_item(tags=["home", secret, "errand"])
    assert item.tags == ["home", "errand"]
    assert "tags" in item.redacted_fields
    with pytest.raises(ValueError, match="tag"):
        make_item(tags=["Home"])
    with pytest.raises(ValueError, match="8"):
        make_item(tags=[f"t{index}" for index in range(9)])


def test_waiting_since_round_trips():
    item = make_item(waiting={"on": "reply", "since": "2026-10-17", "check_back": "2026-10-18"})
    assert item.waiting == {"on": "reply", "since": "2026-10-17", "check_back": "2026-10-18"}
    restored = Item.from_cache(item.to_cache())
    assert restored.tags == []
    assert restored.body_format == "plain"
    assert restored.waiting == item.waiting


def test_query_shortcuts_and_stable_tag_color():
    parsed = parse_query("pack @Home due:today p:1")
    assert parsed.words == ("pack",)
    assert parsed.tags == ("home",)
    assert parsed.due == "today"
    assert parsed.priority == 1
    assert parse_query("due:overdue").due == "overdue"
    assert tag_color("home") == tag_color("home")
    assert tag_color("home", {"home": "teal"}) == "teal"
    assert tag_color("home") in {
        "red",
        "orange",
        "yellow",
        "green",
        "teal",
        "blue",
        "purple",
        "pink",
        "gray",
    }


def test_due_tones_use_end_of_day_for_a_date():
    assert due_tone("2026-10-17", NOW, ZONE) == "amber"
    assert due_tone("2026-10-17 09:00", NOW, ZONE) == "red"
    assert due_tone("2026-10-16", NOW, ZONE) == "red"
    assert due_tone("2026-10-20", NOW, ZONE) == "yellow"
    assert due_tone("2026-10-21", NOW, ZONE) == "neutral"
    assert due_label("2026-10-20 10:00", ZONE) == "Due Tue 10/20 10:00"
    assert due_label("2026-10-20", ZONE) == "Due 10/20"


def test_created_label_uses_the_given_zone():
    pacific = timezone(timedelta(hours=-7))
    stamp = "2026-10-20T04:40:50+00:00"
    assert created_label(stamp, pacific) == "Created Oct 19"
    assert created_label(stamp, UTC) == "Created Oct 20"

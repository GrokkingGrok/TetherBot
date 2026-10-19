# SPDX-License-Identifier: GPL-2.0-or-later
"""Filter JSON and link rules shared by the TetherBot window.

No GTK and no network. The window asks the bridge to apply the filter.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from tetherbot import SCHEMA_VERSION

VIEWS = ("all", "mine", "bots", "waiting", "today")
SORTS = ("due", "priority", "created", "updated")
DONE_DAYS = 7
ASK_TEXT = "About this item"


def list_filter(
    *,
    view: str,
    query: str,
    tags: list[str] | tuple[str, ...],
    sort: str,
    show_done: bool,
) -> dict[str, Any]:
    """The GetItems object for the current window controls."""

    chosen_view = view if view in VIEWS else "all"
    chosen_sort = sort if sort in SORTS else "due"
    spec: dict[str, Any] = {
        "kinds": ["todo"],
        "view": chosen_view,
        "query": query,
        "tags": list(tags),
        "sort": chosen_sort,
    }
    if show_done:
        spec["include_done_days"] = DONE_DAYS
    else:
        spec["status"] = "open"
    return spec


def note_payload(item_key: str) -> tuple[str, str]:
    """Bot id and a SendToBot body that names the item."""

    bot = item_key.split("/", 1)[0]
    payload = {
        "schema": SCHEMA_VERSION,
        "type": "actions",
        "actions": [
            {
                "item": item_key,
                "action": "note",
                "args": {"text": ASK_TEXT},
            }
        ],
    }
    return bot, json.dumps(payload, separators=(",", ":"))


def source_line(item: Mapping[str, Any]) -> str:
    """Bot, routine, and updated time, with the empty parts left out."""

    source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
    bot = source.get("bot") if isinstance(source, Mapping) else ""
    if not isinstance(bot, str) or not bot:
        key = item.get("key")
        bot = key.split("/", 1)[0] if isinstance(key, str) else ""
    routine = source.get("routine") if isinstance(source, Mapping) else ""
    if not isinstance(routine, str):
        routine = ""
    updated = item.get("updated_at")
    if not isinstance(updated, str):
        updated = ""
    return " · ".join(part for part in (bot, routine, updated) if part)


def is_read_only(item: Mapping[str, Any]) -> bool:
    """Closed or already acted items stay visible only as history."""

    if item.get("status") != "open":
        return True
    local = item.get("local")
    if not isinstance(local, Mapping):
        return False
    return bool(local.get("acted") or local.get("resolved") or local.get("done_locally"))


def can_mark_done(item: Mapping[str, Any], outbound: bool) -> bool:
    """Done is offered when the item lists it and the bot has a route."""

    if not outbound or is_read_only(item):
        return False
    actions = item.get("actions")
    return isinstance(actions, list) and "done" in actions


def safe_http_url(href: str) -> str | None:
    """Return ``href`` when it is an http or https URL with no whitespace."""

    if not isinstance(href, str):
        return None
    text = href.strip()
    scheme, sep, _rest = text.partition(":")
    if not sep or scheme.casefold() not in {"http", "https"}:
        return None
    if any(char in text for char in " \t\r\n"):
        return None
    return text

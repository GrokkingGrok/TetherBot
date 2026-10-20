# SPDX-License-Identifier: GPL-2.0-or-later
"""Filter JSON and link rules shared by the TetherBot window.

No GTK and no network. The window asks the bridge to apply the filter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, tzinfo
from typing import Any

from tetherbot import SCHEMA_VERSION
from tetherbot.todos import display_zone, format_local_stamp

VIEWS = ("all", "mine", "bots", "waiting", "today")
SORTS = ("due", "priority", "created", "updated")
DONE_DAYS = 7
ASK_TEXT = "About this item"
_WINDOW_LIVE = frozenset({"Bots"})


def properties_need_reload(names: object) -> bool:
    """True when ``PropertiesChanged`` should reload the open window.

    ``Bots`` carries display names, status dots, and summaries. Item text
    still arrives on ``ItemsChanged``. Other properties, such as ``LastSync``,
    do not rebuild the list.
    """

    if isinstance(names, str):
        return names in _WINDOW_LIVE
    if not isinstance(names, (list, tuple, set, frozenset)):
        return False
    return any(isinstance(name, str) and name in _WINDOW_LIVE for name in names)


def list_filter(
    *,
    view: str,
    query: str,
    tags: list[str] | tuple[str, ...],
    sort: str,
    show_done: bool,
    bots: list[str] | tuple[str, ...] = (),
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
    chosen_bots = [bot for bot in bots if isinstance(bot, str) and bot]
    if chosen_bots:
        spec["bots"] = chosen_bots
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


def source_line(item: Mapping[str, Any], zone: tzinfo | None = None) -> str:
    """Bot, routine, and updated time in the desktop's local zone."""

    source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
    label = item.get("display_name")
    bot = label if isinstance(label, str) and label else ""
    if not bot:
        bot = source.get("bot") if isinstance(source, Mapping) else ""
    if not isinstance(bot, str) or not bot:
        key = item.get("key")
        bot = key.split("/", 1)[0] if isinstance(key, str) else ""
    routine = source.get("routine") if isinstance(source, Mapping) else ""
    if not isinstance(routine, str):
        routine = ""
    updated = item.get("updated_at")
    stamp = ""
    if isinstance(updated, str) and updated:
        stamp = format_local_stamp(updated, zone if zone is not None else display_zone())
    return " · ".join(part for part in (bot, routine, stamp) if part)


def bot_detail_line(bot: Mapping[str, Any], now_unix: int) -> str:
    """Summary, last seen, next run, and open todo count for one bot row."""

    summary = bot.get("summary")
    if not isinstance(summary, str):
        summary = ""
    seen = format_last_seen(bot.get("last_seen"), now_unix)
    nxt = format_next_run(bot.get("next_run"), now_unix)
    todos = open_count_label(bot.get("open_todos"), "todo")
    return " · ".join(part for part in (summary, seen, nxt, todos) if part)


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


def format_last_seen(unix: object, now_unix: int) -> str:
    """Relative last-seen text. ``0`` means the feed has no timestamp."""

    seen = _unix(unix)
    if not seen:
        return "last seen unknown"
    seconds = max(0, int(now_unix) - seen)
    if seconds < 45:
        return "last seen just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"last seen {minutes} m ago"
    hours = minutes // 60
    if hours < 24:
        return f"last seen {hours} h ago"
    return f"last seen {hours // 24} d ago"


def format_next_run(unix: object, now_unix: int) -> str:
    """Relative next-run text. ``0`` means the feed did not set one."""

    when = _unix(unix)
    if not when:
        return ""
    seconds = when - int(now_unix)
    if seconds < 60:
        return "next run due"
    minutes = seconds // 60
    if minutes < 60:
        return f"next run in {minutes} m"
    hours = minutes // 60
    if hours < 24:
        return f"next run in {hours} h"
    return f"next run in {hours // 24} d"


def open_count_label(count: object, noun: str) -> str:
    """``1 open todo`` or ``3 open asks``. A missing count is empty."""

    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return ""
    word = noun if count == 1 else f"{noun}s"
    return f"{count} open {word}"


def _unix(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0


def format_elapsed(seconds: object) -> str:
    """``42:10`` under an hour, ``1:42:10`` from one hour. Negative math is dashes."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
        return "--:--"
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours >= 1:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_top_bar(seconds: object) -> str:
    """Panel text: ``41m`` under an hour, ``1:05`` from one hour. No seconds."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
        return "--:--"
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes = rem // 60
    if hours >= 1:
        return f"{hours}:{minutes:02d}"
    return f"{minutes}m"


_START_CLOCK = re.compile(r"(\d{1,2}):([0-5]\d)\Z")


def parse_start_clock(text: object, now: datetime | None = None) -> int | None:
    """Local ``HH:MM`` as unix seconds. A time still ahead of now is yesterday."""

    if not isinstance(text, str):
        return None
    match = _START_CLOCK.fullmatch(text.strip())
    if match is None:
        return None
    hours = int(match.group(1))
    if hours > 23:
        return None
    moment = now if now is not None else datetime.now().astimezone()
    start = moment.replace(hour=hours, minute=int(match.group(2)), second=0, microsecond=0)
    if start > moment:
        start -= timedelta(days=1)
    return int(start.timestamp())


def format_tracked(seconds: object) -> str:
    """Chip text for a todo's saved total. Empty when nothing has been recorded."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    whole = int(seconds)
    if whole >= 3600:
        hours, rem = divmod(whole, 3600)
        minutes = rem // 60
        return f"{hours}:{minutes:02d} tracked"
    return f"{format_elapsed(whole)} tracked"


def timer_item_key(timer: object) -> str:
    """The open todo a running or paused timer is attached to, or empty."""

    if not isinstance(timer, Mapping):
        return ""
    if timer.get("state") not in {"running", "paused"}:
        return ""
    key = timer.get("item_key")
    return key if isinstance(key, str) else ""


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

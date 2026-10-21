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


def format_duration(seconds: object) -> str:
    """Exact ``H:MM:SS`` for the tracked-time editor. A negative value keeps its sign."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "0:00:00"
    whole = int(seconds)
    sign = "-" if whole < 0 else ""
    whole = abs(whole)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{sign}{hours}:{minutes:02d}:{secs:02d}"


def format_time_record(record: object) -> str:
    """One saved record. An adjustment says so. A session is just its length."""

    if not isinstance(record, Mapping):
        return format_duration(0)
    text = format_duration(record.get("seconds"))
    if record.get("kind") == "adjustment":
        return f"{text} adjustment"
    return text


def parse_tracked_total(text: object) -> int | None:
    """``H:MM:SS``, ``H:MM``, or a minute count such as ``25m``. Empty is not zero."""

    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    minutes = re.fullmatch(r"(\d+)m", raw)
    if minutes is not None:
        return int(minutes.group(1)) * 60
    clock = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", raw)
    if clock is not None:
        return int(clock.group(1)) * 3600 + int(clock.group(2)) * 60 + int(clock.group(3))
    short = re.fullmatch(r"(\d+):([0-5]\d)", raw)
    if short is not None:
        return int(short.group(1)) * 3600 + int(short.group(2)) * 60
    return None


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


UNDO_MS = 5000


def note_done(
    holds: Mapping[str, Any] | list[dict[str, Any]],
    key: str,
    item: dict[str, Any],
    index: int,
    after: str,
    now_ms: int,
    window_ms: int = UNDO_MS,
) -> dict[str, dict[str, Any]]:
    """Remember one cleared row and restart the shared window for every unsent row."""

    span = (
        window_ms
        if isinstance(window_ms, int) and not isinstance(window_ms, bool) and window_ms > 0
        else UNDO_MS
    )
    until = int(now_ms) + span
    updated: dict[str, dict[str, Any]] = {}
    rows = holds.values() if isinstance(holds, Mapping) else holds
    for hold in rows:
        if not isinstance(hold, dict):
            continue
        name = hold.get("key")
        if not isinstance(name, str) or not name:
            continue
        row = dict(hold)
        if not row.get("sent"):
            row["until"] = until
        updated[name] = row
    updated[key] = {
        "key": key,
        "index": index,
        "after": after,
        "until": until,
        "item": dict(item),
        "sent": False,
    }
    return updated


def due_undo_keys(
    holds: Mapping[str, Any] | list[dict[str, Any]],
    now_ms: int,
    *,
    force: bool = False,
) -> list[str]:
    """Keys whose shared window has ended, in the order they were cleared."""

    rows = list(holds.values()) if isinstance(holds, Mapping) else list(holds)
    chosen: list[dict[str, Any]] = []
    now = _millis(now_ms)
    for hold in rows:
        if not isinstance(hold, dict) or hold.get("sent"):
            continue
        key = hold.get("key")
        if not isinstance(key, str) or not key:
            continue
        if force or _millis(hold.get("until")) <= now:
            chosen.append(hold)
    chosen.sort(key=lambda hold: (_millis(hold.get("index")), str(hold.get("key"))))
    return [str(hold["key"]) for hold in chosen]


def undo_fraction(until_ms: object, now_ms: object, window_ms: int = UNDO_MS) -> float:
    """How much of an undo window is left, from 1 down to 0."""

    until = _millis(until_ms)
    now = _millis(now_ms)
    span = (
        window_ms
        if isinstance(window_ms, int) and not isinstance(window_ms, bool) and window_ms > 0
        else UNDO_MS
    )
    remain = until - now
    if remain <= 0:
        return 0.0
    if remain >= span:
        return 1.0
    return remain / span


def merge_undo_items(
    items: list[dict[str, Any]],
    holds: list[dict[str, Any]] | Mapping[str, Any],
    now_ms: int,
    *,
    pin_expired: bool = False,
    window_ms: int = UNDO_MS,
) -> list[dict[str, Any]]:
    """Keep each cleared row at the index it had when it was cleared.

    An expired row stays only while the pointer is still over the list, so
    the rows under the cursor do not jump.
    """

    rows = list(holds.values()) if isinstance(holds, Mapping) else list(holds)
    active: dict[str, dict[str, Any]] = {}
    for hold in rows:
        if not isinstance(hold, dict):
            continue
        key = hold.get("key")
        item = hold.get("item")
        if not isinstance(key, str) or not key or not isinstance(item, dict):
            continue
        until = _millis(hold.get("until"))
        live = until > now_ms and not hold.get("sent")
        if not live and not pin_expired:
            continue
        active[key] = hold
    base: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if isinstance(key, str) and key in active:
            continue
        base.append(dict(item))
    ordered = sorted(active.values(), key=lambda hold: _millis(hold.get("index")))
    waiting: list[dict[str, Any]] = []
    for hold in ordered:
        if not _insert_hold(base, hold, now_ms, window_ms):
            waiting.append(hold)
    for hold in waiting:
        if _insert_hold(base, hold, now_ms, window_ms):
            continue
        item = _undo_item(hold, now_ms, window_ms)
        index = _millis(hold.get("index"))
        if index < 0:
            index = 0
        if index > len(base):
            index = len(base)
        base.insert(index, item)
    return base


def _undo_item(hold: dict[str, Any], now_ms: int, window_ms: int = UNDO_MS) -> dict[str, Any]:
    item = dict(hold["item"])
    until = _millis(hold.get("until"))
    live = until > now_ms and not hold.get("sent")
    item["_undo"] = {
        "until": until,
        "fraction": undo_fraction(until, now_ms, window_ms) if live else 0.0,
        "live": live,
    }
    return item


def _insert_hold(
    base: list[dict[str, Any]],
    hold: dict[str, Any],
    now_ms: int,
    window_ms: int = UNDO_MS,
) -> bool:
    """Place the row just before the neighbor it had when it was cleared."""

    after = hold.get("after")
    if not isinstance(after, str) or not after:
        return False
    for index, item in enumerate(base):
        if item.get("key") == after:
            base.insert(index, _undo_item(hold, now_ms, window_ms))
            return True
    return False


def _millis(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


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

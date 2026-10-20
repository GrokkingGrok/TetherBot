# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared todo filters, tag colors, and chip labels.

The popup and the window both read GetItems, so the rules live here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

PALETTE = (
    "red",
    "orange",
    "yellow",
    "green",
    "teal",
    "blue",
    "purple",
    "pink",
    "gray",
)
PALETTE_NAMES = frozenset(PALETTE)
VIEWS = frozenset({"all", "mine", "bots", "waiting", "today"})
SORTS = frozenset({"due", "priority", "created", "updated"})
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def display_zone() -> tzinfo:
    """The desktop's local zone. Chip dates follow this, not the bridge clock."""

    zone = datetime.now().astimezone().tzinfo
    return zone if zone is not None else UTC


def format_local_stamp(value: str, zone: tzinfo) -> str:
    """``Oct 19, 9:40 PM``. An unusable timestamp is an empty string."""

    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    local = moment.astimezone(zone)
    hour24 = local.hour
    suffix = "AM" if hour24 < 12 else "PM"
    hour = hour24 % 12 or 12
    month = _MONTHS[local.month - 1]
    return f"{month} {local.day}, {hour}:{local.minute:02d} {suffix}"


@dataclass(frozen=True)
class ParsedQuery:
    """A search box value split into words and shortcuts."""

    words: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    due: str | None = None
    priority: int | None = None


def tag_color(tag: str, overrides: Mapping[str, str] | None = None) -> str:
    """Return a palette name. The hash is stable across machines."""

    if overrides is not None:
        chosen = overrides.get(tag)
        if isinstance(chosen, str) and chosen in PALETTE_NAMES:
            return chosen
    value = 2166136261
    for byte in tag.encode("utf-8"):
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return PALETTE[value % len(PALETTE)]


def parse_query(text: str) -> ParsedQuery:
    """Split ``@tag``, ``due:today``, ``due:overdue``, ``p:1``, and keywords."""

    words: list[str] = []
    tags: list[str] = []
    due: str | None = None
    priority: int | None = None
    for token in text.split():
        lowered = token.casefold()
        if lowered.startswith("@") and len(token) > 1:
            tags.append(token[1:].casefold())
            continue
        if lowered in {"due:today", "due:overdue"}:
            due = lowered.split(":", 1)[1]
            continue
        if lowered.startswith("p:") and lowered[2:] in {"1", "2", "3"}:
            priority = int(lowered[2:])
            continue
        words.append(lowered)
    return ParsedQuery(tuple(words), tuple(tags), due, priority)


def due_deadline(due: str | None, zone: tzinfo) -> datetime | None:
    """When a due value becomes overdue. A date alone lasts until the end of that day."""

    parsed = _due_clock(due, zone)
    if parsed is None:
        return None
    return parsed[1]


def due_tone(due: str | None, now: datetime, zone: tzinfo) -> str:
    """``red``, ``amber``, ``yellow``, ``neutral``, or empty when there is no due date."""

    parsed = _due_clock(due, zone)
    if parsed is None:
        return ""
    day, deadline = parsed
    local = now.astimezone(zone)
    if deadline < local:
        return "red"
    if day == local.date():
        return "amber"
    if local.date() < day <= local.date() + timedelta(days=3):
        return "yellow"
    return "neutral"


def due_is_today(due: str | None, now: datetime, zone: tzinfo) -> bool:
    parsed = _due_clock(due, zone)
    if parsed is None:
        return False
    return parsed[0] == now.astimezone(zone).date()


def due_is_overdue(due: str | None, now: datetime, zone: tzinfo) -> bool:
    return due_tone(due, now, zone) == "red"


def due_label(due: str | None, zone: tzinfo) -> str:
    parsed = _due_clock(due, zone)
    if parsed is None or due is None:
        return ""
    day, _deadline = parsed
    stamp = f"{day.month}/{day.day}"
    if " " in due:
        weekday = _WEEKDAYS[day.weekday()]
        clock = due.split(" ", 1)[1]
        return f"Due {weekday} {stamp} {clock}"
    return f"Due {stamp}"


def created_label(created: str, zone: tzinfo) -> str:
    try:
        moment = datetime.fromisoformat(created)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        return ""
    day = moment.astimezone(zone).date()
    return f"Created {_MONTHS[day.month - 1]} {day.day}"


def priority_tone(priority: int | None) -> str:
    if priority == 1:
        return "red"
    if priority == 2:
        return "amber"
    if priority == 3:
        return "neutral"
    return ""


def chips(item: object, now: datetime, zone: tzinfo, overrides: Mapping[str, str]) -> dict:
    """Labels and palette tones for one item. The feed file does not store these."""

    due = getattr(item, "due", None)
    priority = getattr(item, "priority", None)
    tags = list(getattr(item, "tags", ()) or ())
    waiting = getattr(item, "waiting", None)
    created = getattr(item, "created", "")
    row: dict = {
        "created": {"label": created_label(created, zone), "tone": "green"},
        "tags": [
            {"tag": tag, "label": f"@{tag}", "tone": tag_color(tag, overrides)} for tag in tags
        ],
    }
    label = due_label(due, zone)
    if label:
        row["due"] = {"label": label, "tone": due_tone(due, now, zone)}
    if isinstance(priority, int):
        row["priority"] = {"label": f"#{priority}", "tone": priority_tone(priority)}
    if isinstance(waiting, Mapping):
        on = waiting.get("on")
        text = f"Waiting on {on}" if isinstance(on, str) and on else "Waiting"
        row["waiting"] = {"label": text, "tone": "neutral"}
    return row


def matches(
    item: object,
    *,
    required_tags: Sequence[str],
    query: ParsedQuery,
    view: str,
    now: datetime,
    zone: tzinfo,
) -> bool:
    """Return whether an open item belongs in this filter."""

    tags = {tag.casefold() for tag in getattr(item, "tags", ()) or ()}
    needed = {tag.casefold() for tag in required_tags}
    needed.update(query.tags)
    if not needed <= tags:
        return False
    if query.priority is not None and getattr(item, "priority", None) != query.priority:
        return False
    due = getattr(item, "due", None)
    if query.due == "today" and not due_is_today(due, now, zone):
        return False
    if query.due == "overdue" and not due_is_overdue(due, now, zone):
        return False
    if query.words:
        haystack = " ".join(
            [
                str(getattr(item, "title", "")),
                str(getattr(item, "body", "")),
                " ".join(getattr(item, "tags", ()) or ()),
            ]
        ).casefold()
        if any(word not in haystack for word in query.words):
            return False
    owner = getattr(item, "owner", None)
    if view == "mine" and owner == "bot":
        return False
    if view == "bots" and owner != "bot":
        return False
    if view == "waiting" and not getattr(item, "waiting", None):
        return False
    if view == "today" and not (due_is_today(due, now, zone) or due_is_overdue(due, now, zone)):
        return False
    return True


def sort_key(item: object, sort: str, now: datetime, zone: tzinfo) -> tuple:
    """Overdue items first, then the selected field."""

    overdue = 0 if due_is_overdue(getattr(item, "due", None), now, zone) else 1
    if sort == "priority":
        priority = getattr(item, "priority", None)
        secondary: object = priority if isinstance(priority, int) else 9
    elif sort == "created":
        secondary = str(getattr(item, "created", ""))
    elif sort == "updated":
        secondary = str(getattr(item, "updated_at", ""))
    else:
        deadline = due_deadline(getattr(item, "due", None), zone)
        secondary = "" if deadline is None else deadline.isoformat()
        if deadline is None:
            overdue = 2
    return (overdue, secondary, str(getattr(item, "key", "")))


def _due_clock(due: str | None, zone: tzinfo) -> tuple[date, datetime] | None:
    if not isinstance(due, str) or not due:
        return None
    if len(due) == 10:
        try:
            day = datetime.strptime(due, "%Y-%m-%d").date()
        except ValueError:
            return None
        deadline = datetime.combine(day, time(23, 59, 59), tzinfo=zone)
        return day, deadline
    if len(due) == 16 and due[10] == " ":
        try:
            moment = datetime.strptime(due, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        local = moment.replace(tzinfo=zone)
        return local.date(), local
    return None

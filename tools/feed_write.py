#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Write ``feed/<bot>.json`` through the GitHub contents API.

Standalone, stdlib only, Python 3.10+. Schema rules are duplicated from
docs/PROTOCOL.md so this script does not import the desktop bridge. It
never reads or writes ``desktop/*``.

The token is read from the environment variable named by ``--token-env``
and sent only in the ``Authorization`` header.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# datetime.UTC arrived in 3.11. This file stays runnable on 3.10.
UTC = timezone.utc  # noqa: UP017

SCHEMA = "tetherbot/1"
API_ROOT = "https://api.github.com"
USER_AGENT = "tetherbot-feed-write"
SUMMARY_LIMIT = 200
MAX_ATTEMPTS = 4  # first write plus up to 3 conflict retries

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_AUTH = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_TRANSPORT = 5

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BOT = re.compile(r"^[a-z0-9-]{1,64}$")
_ID = re.compile(r"^[a-z0-9-]{3,64}$")
_TAG = re.compile(r"^[a-z0-9_-]{1,32}$")
_FEED_PATH = re.compile(r"^feed/[a-z0-9-]{1,64}\.json$")
_SCHEMA_MAJOR = re.compile(r"^tetherbot/1(?:\.\d+)?$")
_DUE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DUE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_PREFIX = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(?:ghp_|github_pat_|sk-|AKIA)")
_DIGITS = re.compile(r"\d{9,}")
_HEX = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")

_STATES = frozenset({"idle", "working", "needs_you", "error"})
_KINDS = frozenset({"ask", "todo", "watch", "notification", "status"})
_ITEM_STATUSES = frozenset({"open", "done", "dropped", "expired"})
_ACTIONS = frozenset({"approve", "veto", "done", "snooze", "open_chat"})
_CLOSE_STATUSES = frozenset({"done", "dropped"})
_PALETTE = frozenset(
    {"red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"}
)
_OWNERS = frozenset({"user", "bot"})

Request = Callable[[str, str, dict[str, str], bytes | None], tuple[int, object, bytes]]


class FeedWriteError(Exception):
    """A failure the bot can report in one line. ``code`` is the exit status."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class _Conflict(Exception):
    """The contents API rejected the file sha. The caller refetches."""


def looks_like_secret(text: str) -> bool:
    """Return whether ``text`` matches the protocol secret guard."""

    if _PREFIX.search(text) or _DIGITS.search(text):
        return True
    return bool(_HEX.search(text) or _B64.search(text))


def assert_feed_path(path: str) -> None:
    """Refuse every path except ``feed/<bot>.json``."""

    if (
        not isinstance(path, str)
        or _FEED_PATH.fullmatch(path) is None
        or path.startswith("desktop/")
        or "/desktop/" in f"/{path}"
    ):
        raise FeedWriteError(
            "refusing to write desktop/ or any path other than feed/<bot>.json",
            EXIT_USAGE,
        )


def feed_path(bot: str) -> str:
    """Return the only path this tool edits."""

    if not isinstance(bot, str) or _BOT.fullmatch(bot) is None:
        raise FeedWriteError("bot id must match [a-z0-9-]{1,64}", EXIT_USAGE)
    path = f"feed/{bot}.json"
    assert_feed_path(path)
    return path


def parse_repo(value: str) -> str:
    """Return ``owner/name``. The token is never part of this string."""

    if not isinstance(value, str) or _REPO.fullmatch(value) is None:
        raise FeedWriteError("repo must be owner/name", EXIT_USAGE)
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise FeedWriteError("repo must be owner/name", EXIT_USAGE)
    return value


def _reject_secret(text: str, field: str) -> None:
    if looks_like_secret(text):
        raise FeedWriteError(f"{field} looks like a secret", EXIT_USAGE)


def _require_title(value: object, field: str = "title") -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise FeedWriteError(f"{field} must be a single line", EXIT_USAGE)
    if not 1 <= len(value) <= 120:
        raise FeedWriteError(f"{field} must be 1 to 120 characters", EXIT_USAGE)
    _reject_secret(value, field)
    return value


def _optional_body(value: object, *, limit: int = 1000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FeedWriteError("body must be a string", EXIT_USAGE)
    if len(value) > limit:
        raise FeedWriteError(f"body must be at most {limit} characters", EXIT_USAGE)
    _reject_secret(value, "body")
    return value


def _body_limit(kind: str, body_format: str) -> int:
    if kind == "todo" and body_format == "markdown":
        return 8000
    return 1000


def _read_body_file(path: str) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise FeedWriteError("body file path is invalid", EXIT_USAGE)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise FeedWriteError("body file could not be read", EXIT_USAGE) from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.rstrip("\n")


def _clean_tag(value: str) -> str:
    if not isinstance(value, str) or _TAG.fullmatch(value) is None:
        raise FeedWriteError(
            "a tag must be 1 to 32 characters of a-z, 0-9, hyphen, or underscore",
            EXIT_USAGE,
        )
    _reject_secret(value, "tag")
    return value


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise FeedWriteError(
            f"{field} must be an ISO 8601 timestamp with an offset",
            EXIT_USAGE,
        )
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FeedWriteError(
            f"{field} must be an ISO 8601 timestamp with an offset",
            EXIT_USAGE,
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise FeedWriteError(f"{field} must include a timezone offset", EXIT_USAGE)
    return parsed


def normalize_timestamp(value: object, field: str) -> str:
    """Return an ISO 8601 timestamp with an offset."""

    return _parse_timestamp(value, field).isoformat()


def stamp(moment: datetime) -> str:
    """Format ``moment`` as UTC with an explicit offset."""

    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise FeedWriteError("clock must be timezone-aware", EXIT_USAGE)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def normalize_due(value: str) -> str:
    """Accept a protocol due or an ISO 8601 timestamp. Store the protocol form."""

    if not isinstance(value, str) or not value:
        raise FeedWriteError("due must be YYYY-MM-DD or YYYY-MM-DD HH:MM", EXIT_USAGE)
    if _DUE_DATE.fullmatch(value):
        _calendar_date(value, "%Y-%m-%d")
        return value
    if _DUE_TIME.fullmatch(value):
        _calendar_date(value, "%Y-%m-%d %H:%M")
        return value
    parsed = _parse_timestamp(value, "due")
    local = parsed
    if (
        local.hour == 0
        and local.minute == 0
        and local.second == 0
        and local.microsecond == 0
    ):
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d %H:%M")


def _calendar_date(value: str, fmt: str) -> None:
    try:
        datetime.strptime(value, fmt)
    except ValueError as exc:
        raise FeedWriteError("due must be a real calendar date", EXIT_USAGE) from exc


def parse_item_id(bot: str, key: str) -> str:
    """Accept an item id or ``<bot>/<id>``. The prefix must match ``bot``."""

    if not isinstance(key, str) or not key:
        raise FeedWriteError("key is required", EXIT_USAGE)
    item_id = key
    if "/" in key:
        prefix, item_id = key.split("/", 1)
        if prefix != bot:
            raise FeedWriteError("key prefix must match --bot", EXIT_USAGE)
    if _ID.fullmatch(item_id) is None:
        raise FeedWriteError("item id must match [a-z0-9-]{3,64}", EXIT_USAGE)
    return item_id


def dumps_feed(doc: dict) -> str:
    """Pretty-print a feed file with a trailing newline."""

    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def empty_feed(bot: str, moment: datetime) -> dict:
    """A new feed file. Status stays absent until the status command."""

    return {
        "schema": SCHEMA,
        "bot": bot,
        "updated_at": stamp(moment),
        "items": [],
    }


def _items(doc: dict) -> list:
    items = doc.get("items")
    if not isinstance(items, list):
        raise FeedWriteError("items must be a list", EXIT_USAGE)
    return items


def validate_feed(doc: object, bot: str) -> None:
    """Reject a file this tool should not commit. Unknown fields are kept."""

    if not isinstance(doc, dict):
        raise FeedWriteError("feed file must be a JSON object", EXIT_USAGE)
    schema = doc.get("schema")
    if not isinstance(schema, str) or _SCHEMA_MAJOR.fullmatch(schema) is None:
        shown = schema if isinstance(schema, str) else ""
        raise FeedWriteError(f"unsupported schema {shown}".rstrip(), EXIT_USAGE)
    if doc.get("bot") != bot:
        raise FeedWriteError("feed bot does not match --bot", EXIT_USAGE)
    _parse_timestamp(doc.get("updated_at"), "updated_at")
    status = doc.get("status")
    if status is not None:
        _validate_status(status)
    if "tag_colors" in doc:
        _validate_tag_colors(doc.get("tag_colors"))
    for item in _items(doc):
        _validate_item(item, bot)


def _validate_status(status: object) -> None:
    if not isinstance(status, dict):
        raise FeedWriteError("status must be an object", EXIT_USAGE)
    state = status.get("state")
    if state is not None and state not in _STATES:
        raise FeedWriteError("status.state must be idle, working, needs_you, or error", EXIT_USAGE)
    summary = status.get("summary")
    if summary is not None:
        _require_summary(summary)
    for field in ("last_run", "next_run"):
        if status.get(field) is not None:
            _parse_timestamp(status.get(field), field)


def _require_summary(value: object) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise FeedWriteError("summary must be a single line", EXIT_USAGE)
    if not 1 <= len(value) <= SUMMARY_LIMIT:
        raise FeedWriteError(f"summary must be 1 to {SUMMARY_LIMIT} characters", EXIT_USAGE)
    _reject_secret(value, "summary")
    return value


def _validate_item(item: object, bot: str) -> None:
    if not isinstance(item, dict):
        raise FeedWriteError("item must be an object", EXIT_USAGE)
    item_id = item.get("id")
    if not isinstance(item_id, str) or _ID.fullmatch(item_id) is None:
        raise FeedWriteError("item id must match [a-z0-9-]{3,64}", EXIT_USAGE)
    if item.get("kind") not in _KINDS:
        raise FeedWriteError("item kind is not in the protocol", EXIT_USAGE)
    _require_title(item.get("title"))
    body_format = item.get("body_format", "plain")
    if body_format not in {"plain", "markdown"}:
        raise FeedWriteError("body_format must be plain or markdown", EXIT_USAGE)
    if "body" in item:
        _optional_body(item.get("body"), limit=_body_limit(str(item.get("kind")), str(body_format)))
    tags = item.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 8:
        raise FeedWriteError("tags has a maximum of 8", EXIT_USAGE)
    for tag in tags:
        if not isinstance(tag, str):
            raise FeedWriteError("tags must be a list of strings", EXIT_USAGE)
        _clean_tag(tag)
    if item.get("status") not in _ITEM_STATUSES:
        raise FeedWriteError("item status must be open, done, dropped, or expired", EXIT_USAGE)
    _parse_timestamp(item.get("created"), "created")
    _parse_timestamp(item.get("updated_at"), "updated_at")
    if item.get("due") is not None:
        _existing_due(item.get("due"))
    todo_kind = item.get("todo_kind")
    if todo_kind is not None:
        if item.get("kind") != "todo" or todo_kind not in {"task", "bill"}:
            raise FeedWriteError("todo_kind must be task or bill on a todo", EXIT_USAGE)
    amount = item.get("amount")
    if isinstance(amount, str):
        _reject_secret(amount, "amount")
    waiting = item.get("waiting")
    if isinstance(waiting, dict) and isinstance(waiting.get("on"), str):
        _reject_secret(waiting["on"], "waiting.on")
    actions = item.get("actions", [])
    if not isinstance(actions, list) or any(entry not in _ACTIONS for entry in actions):
        raise FeedWriteError("actions must be a subset of the protocol actions", EXIT_USAGE)
    source = item.get("source")
    if not isinstance(source, dict) or source.get("bot") != bot:
        raise FeedWriteError("source.bot must match the feed bot", EXIT_USAGE)
    routine = source.get("routine")
    if routine is not None and (not isinstance(routine, str) or not routine):
        raise FeedWriteError("source.routine must be a string", EXIT_USAGE)
    if isinstance(routine, str):
        _reject_secret(routine, "source.routine")


def _validate_tag_colors(value: object) -> None:
    if not isinstance(value, dict):
        raise FeedWriteError("tag_colors must be an object", EXIT_USAGE)
    for tag, color in value.items():
        if not isinstance(tag, str):
            raise FeedWriteError("tag_colors keys must be tags", EXIT_USAGE)
        _clean_tag(tag)
        if color not in _PALETTE:
            names = ", ".join(sorted(_PALETTE))
            raise FeedWriteError(f"tag color must be a palette name: {names}", EXIT_USAGE)


def _existing_due(value: object) -> None:
    if not isinstance(value, str) or (
        _DUE_DATE.fullmatch(value) is None and _DUE_TIME.fullmatch(value) is None
    ):
        raise FeedWriteError("due must be YYYY-MM-DD or YYYY-MM-DD HH:MM", EXIT_USAGE)
    fmt = "%Y-%m-%d" if _DUE_DATE.fullmatch(value) else "%Y-%m-%d %H:%M"
    _calendar_date(value, fmt)


def _public_item(bot: str, item: dict) -> dict:
    shown = {"key": f"{bot}/{item['id']}"}
    shown.update(item)
    return shown


def _match_open(items: list, kind: str, title: str, body: str) -> dict | None:
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != kind or item.get("status") != "open":
            continue
        if item.get("title") != title:
            continue
        if (item.get("body") or "") == body:
            return item
    return None


def _next_id(bot: str, items: list, moment: datetime) -> str:
    day = moment.astimezone(UTC).strftime("%Y%m%d")
    prefix = f"{bot}-{day}-"
    used: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.startswith(prefix):
            continue
        suffix = item_id[len(prefix) :]
        if suffix.isdigit():
            used.add(int(suffix))
    number = 1
    while number in used:
        number += 1
    if number > 99:
        raise FeedWriteError("no free id for today; pass --key", EXIT_USAGE)
    item_id = f"{prefix}{number:02d}"
    if _ID.fullmatch(item_id) is None:
        raise FeedWriteError("auto id does not fit; pass --key", EXIT_USAGE)
    return item_id


def _insert_status(doc: dict, status: dict) -> None:
    if "status" in doc and isinstance(doc["status"], dict):
        return
    rebuilt: dict = {}
    placed = False
    for key, value in doc.items():
        if key == "items" and not placed:
            rebuilt["status"] = status
            placed = True
        if key == "status":
            continue
        rebuilt[key] = value
    if not placed:
        rebuilt["status"] = status
    doc.clear()
    doc.update(rebuilt)


def add_item(
    doc: dict,
    *,
    bot: str,
    kind: str,
    title: str,
    body: str,
    moment: datetime,
    actions: list[str],
    key: str | None = None,
    due: str | None = None,
    todo_kind: str | None = None,
    tags: list[str] | None = None,
    priority: int | None = None,
    owner: str | None = None,
    waiting_on: str | None = None,
    markdown: bool = False,
) -> tuple[bool, dict, str]:
    """Append an ask or todo. An open item with the same title and body is reused."""

    title = _require_title(title)
    body_format = "markdown" if markdown and kind == "todo" else "plain"
    body = _optional_body(body, limit=_body_limit(kind, body_format))
    if due is not None:
        due = normalize_due(due)
    if todo_kind is not None and (kind != "todo" or todo_kind not in {"task", "bill"}):
        raise FeedWriteError("todo_kind must be task or bill", EXIT_USAGE)
    clean_tags = [_clean_tag(tag) for tag in (tags or [])]
    if len(clean_tags) > 8 or len(set(clean_tags)) != len(clean_tags):
        raise FeedWriteError("tags has a maximum of 8 unique tags", EXIT_USAGE)
    if priority is not None and priority not in {1, 2, 3}:
        raise FeedWriteError("priority must be 1, 2, or 3", EXIT_USAGE)
    if owner is not None and owner not in _OWNERS:
        raise FeedWriteError("owner must be user or bot", EXIT_USAGE)
    waiting = _waiting_on(waiting_on, moment) if waiting_on else None
    items = _items(doc)
    existing = _match_open(items, kind, title, body)
    if existing is not None:
        return False, _public_item(bot, existing), ""
    if key is None:
        item_id = _next_id(bot, items, moment)
    else:
        item_id = parse_item_id(bot, key)
        if any(isinstance(item, dict) and item.get("id") == item_id for item in items):
            raise FeedWriteError(f"item id {item_id} already exists", EXIT_USAGE)
    when = stamp(moment)
    item: dict = {
        "id": item_id,
        "kind": kind,
        "title": title,
    }
    if body:
        item["body"] = body
    if body_format == "markdown":
        item["body_format"] = "markdown"
    item["status"] = "open"
    item["created"] = when
    item["updated_at"] = when
    if due is not None:
        item["due"] = due
    if priority is not None:
        item["priority"] = priority
    if owner is not None:
        item["owner"] = owner
    if waiting is not None:
        item["waiting"] = waiting
    if todo_kind is not None:
        item["todo_kind"] = todo_kind
    if clean_tags:
        item["tags"] = clean_tags
    item["actions"] = list(actions)
    item["notify"] = True
    item["source"] = {"bot": bot}
    items.append(item)
    doc["updated_at"] = when
    label = "todo" if kind == "todo" else "ask"
    return True, _public_item(bot, item), f"Add {label} {item_id}: {title}"


def _waiting_on(text: str, moment: datetime) -> dict[str, str]:
    if not isinstance(text, str) or not text or len(text) > 40 or "\n" in text or "\r" in text:
        raise FeedWriteError("waiting-on must be a single line of 1 to 40 characters", EXIT_USAGE)
    _reject_secret(text, "waiting.on")
    return {"on": text, "since": moment.astimezone(UTC).strftime("%Y-%m-%d")}


def _find_item(doc: dict, bot: str, key: str) -> dict:
    item_id = parse_item_id(bot, key)
    for item in _items(doc):
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    raise FeedWriteError(f"item {bot}/{item_id} was not found", EXIT_NOT_FOUND)


def edit_item(
    doc: dict,
    *,
    bot: str,
    key: str,
    moment: datetime,
    title: str | None = None,
    body: str | None = None,
    due: str | None = None,
    clear_due: bool = False,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    priority: int | None = None,
    waiting_on: str | None = None,
    clear_waiting: bool = False,
    markdown: bool | None = None,
) -> tuple[bool, dict, str]:
    """Change fields the bot owns. An empty edit does not write."""

    if clear_due and due is not None:
        raise FeedWriteError("pass due or clear-due, not both", EXIT_USAGE)
    if clear_waiting and waiting_on is not None:
        raise FeedWriteError("pass waiting-on or clear-waiting, not both", EXIT_USAGE)
    found = _find_item(doc, bot, key)
    changed = False
    if title is not None:
        title = _require_title(title)
        if found.get("title") != title:
            found["title"] = title
            changed = True
    if markdown is True:
        if found.get("body_format") != "markdown":
            found["body_format"] = "markdown"
            changed = True
    elif markdown is False and found.get("body_format") == "markdown":
        found.pop("body_format", None)
        changed = True
    if body is not None:
        kind = str(found.get("kind") or "")
        body_format = "markdown" if found.get("body_format") == "markdown" else "plain"
        body = _optional_body(body, limit=_body_limit(kind, body_format))
        if body:
            if found.get("body") != body:
                found["body"] = body
                changed = True
        elif "body" in found:
            found.pop("body")
            changed = True
    if due is not None:
        due = normalize_due(due)
        if found.get("due") != due:
            found["due"] = due
            changed = True
    if clear_due and "due" in found:
        found.pop("due")
        changed = True
    if priority is not None:
        if priority not in {1, 2, 3}:
            raise FeedWriteError("priority must be 1, 2, or 3", EXIT_USAGE)
        if found.get("priority") != priority:
            found["priority"] = priority
            changed = True
    tags = found.get("tags")
    if not isinstance(tags, list):
        tags = []
    tag_list = [tag for tag in tags if isinstance(tag, str)]
    for tag in add_tags or []:
        clean = _clean_tag(tag)
        if clean not in tag_list:
            tag_list.append(clean)
            changed = True
    for tag in remove_tags or []:
        clean = _clean_tag(tag)
        if clean in tag_list:
            tag_list = [entry for entry in tag_list if entry != clean]
            changed = True
    if len(tag_list) > 8:
        raise FeedWriteError("tags has a maximum of 8", EXIT_USAGE)
    if tag_list:
        if found.get("tags") != tag_list:
            found["tags"] = tag_list
            changed = True
    elif "tags" in found:
        found.pop("tags")
        changed = True
    if waiting_on is not None:
        waiting = _waiting_on(waiting_on, moment)
        if found.get("waiting") != waiting:
            found["waiting"] = waiting
            changed = True
    if clear_waiting and "waiting" in found:
        found.pop("waiting")
        changed = True
    if not changed:
        return False, _public_item(bot, found), ""
    when = stamp(moment)
    found["updated_at"] = when
    doc["updated_at"] = when
    return True, _public_item(bot, found), f"Edit {found['id']}"


def set_tag_color(
    doc: dict,
    *,
    tag: str,
    color: str,
    moment: datetime,
) -> tuple[bool, dict, str]:
    """Set one feed-level palette entry."""

    tag = _clean_tag(tag)
    if color not in _PALETTE:
        names = ", ".join(sorted(_PALETTE))
        raise FeedWriteError(f"tag color must be a palette name: {names}", EXIT_USAGE)
    colors = doc.get("tag_colors")
    if not isinstance(colors, dict):
        colors = {}
        _insert_before_items(doc, "tag_colors", colors)
    if colors.get(tag) == color:
        return False, {"tag": tag, "color": color}, ""
    colors[tag] = color
    doc["tag_colors"] = colors
    doc["updated_at"] = stamp(moment)
    return True, {"tag": tag, "color": color}, f"Set color for {tag}"


def _insert_before_items(doc: dict, key: str, value: object) -> None:
    rebuilt: dict = {}
    placed = False
    for name, current in doc.items():
        if name == "items" and not placed:
            rebuilt[key] = value
            placed = True
        if name == key:
            continue
        rebuilt[name] = current
    if not placed:
        rebuilt[key] = value
    doc.clear()
    doc.update(rebuilt)


def set_item_status(
    doc: dict,
    *,
    bot: str,
    key: str,
    status: str,
    moment: datetime,
) -> tuple[bool, dict, str]:
    """Set one item's status. A matching status is left unchanged."""

    if status not in _ITEM_STATUSES:
        raise FeedWriteError("status must be open, done, or dropped", EXIT_USAGE)
    item_id = parse_item_id(bot, key)
    found = None
    for item in _items(doc):
        if isinstance(item, dict) and item.get("id") == item_id:
            found = item
            break
    if found is None:
        raise FeedWriteError(f"item {bot}/{item_id} was not found", EXIT_NOT_FOUND)
    if found.get("status") == status:
        return False, _public_item(bot, found), ""
    when = stamp(moment)
    found["status"] = status
    found["updated_at"] = when
    doc["updated_at"] = when
    if status == "open":
        message = f"Reopen {item_id}"
    elif status == "dropped":
        message = f"Drop {item_id}"
    else:
        message = f"Close {item_id}"
    return True, _public_item(bot, found), message


def set_feed_status(
    doc: dict,
    *,
    state: str,
    summary: str,
    moment: datetime,
    next_run: str | None = None,
    last_run: str | None = None,
) -> tuple[bool, dict, str]:
    """Replace the file status block and bump the file ``updated_at``."""

    if state not in _STATES:
        raise FeedWriteError("state must be idle, working, needs_you, or error", EXIT_USAGE)
    summary = _require_summary(summary)
    status = doc.get("status")
    if not isinstance(status, dict):
        status = {}
        _insert_status(doc, status)
    status["state"] = state
    status["summary"] = summary
    if last_run is not None:
        status["last_run"] = normalize_timestamp(last_run, "last_run")
    if next_run is not None:
        status["next_run"] = normalize_timestamp(next_run, "next_run")
    when = stamp(moment)
    doc["updated_at"] = when
    payload = {"updated_at": when, "status": status}
    return True, payload, "Update feed status"


def list_items(doc: dict, bot: str, *, open_only: bool) -> list[dict]:
    """Return feed items, with ``key`` added for the caller. The file is unchanged."""

    rows = []
    for item in _items(doc):
        if not isinstance(item, dict):
            continue
        if open_only and item.get("status") != "open":
            continue
        rows.append(_public_item(bot, item))
    return rows


def _token_from_env(name: str, environ: dict[str, str]) -> str:
    if not name or not name.isidentifier():
        raise FeedWriteError("token env name must be an identifier", EXIT_USAGE)
    token = environ.get(name, "")
    if not token or token.strip() != token or any(char in token for char in "\r\n\x00"):
        raise FeedWriteError(
            f"set {name} to a GitHub token with Contents access on this repository",
            EXIT_USAGE,
        )
    return token


def _auth_error(status: int) -> FeedWriteError:
    return FeedWriteError(
        f"GitHub rejected the token (HTTP {status}). "
        "It may be expired or lack Contents access.",
        EXIT_AUTH,
    )


class ContentsClient:
    """GET and PUT one contents path. The token stays in the header."""

    def __init__(self, repo: str, token: str, request: Request) -> None:
        self.repo = parse_repo(repo)
        self._token = token
        self._request = request

    def _url(self, path: str) -> str:
        assert_feed_path(path)
        owner, name = self.repo.split("/", 1)
        quoted = urllib.parse.quote(path, safe="/")
        return f"{API_ROOT}/repos/{owner}/{name}/contents/{quoted}"

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _call(
        self,
        method: str,
        url: str,
        body: bytes | None,
        *,
        json_body: bool,
    ) -> tuple[int, bytes]:
        parsed = urllib.parse.urlsplit(url)
        if self._token in parsed.netloc or self._token in parsed.query:
            raise FeedWriteError("refusing to put the token in a URL", EXIT_USAGE)
        try:
            status, _headers, payload = self._request(
                method,
                url,
                self._headers(json_body=json_body),
                body,
            )
        except FeedWriteError:
            raise
        except Exception as exc:
            raise FeedWriteError("GitHub request failed", EXIT_TRANSPORT) from exc
        if status in {301, 302, 303, 307, 308}:
            raise FeedWriteError(
                f"GitHub redirected the contents request (HTTP {status})",
                EXIT_TRANSPORT,
            )
        return status, payload

    def read(self, path: str) -> tuple[dict | None, str | None]:
        """Return ``(document, sha)``. A missing file is ``(None, None)``."""

        assert_feed_path(path)
        status, payload = self._call("GET", self._url(path), None, json_body=False)
        if status == 404:
            return None, None
        if status in {401, 403}:
            raise _auth_error(status)
        if status != 200:
            raise FeedWriteError(f"GitHub contents read failed (HTTP {status})", EXIT_TRANSPORT)
        try:
            parsed = json.loads(payload.decode("utf-8"))
            encoded = parsed["content"]
            sha = parsed["sha"]
            raw = base64.b64decode(encoded, validate=False)
            doc = json.loads(raw.decode("utf-8"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FeedWriteError("feed file is not valid JSON", EXIT_USAGE) from exc
        if not isinstance(doc, dict) or not isinstance(sha, str) or not sha:
            raise FeedWriteError("feed file is not valid JSON", EXIT_USAGE)
        return doc, sha

    def write(self, path: str, text: str, sha: str | None, message: str) -> None:
        """PUT ``text``. A stale sha raises ``_Conflict``."""

        assert_feed_path(path)
        if not message or "\n" in message or "\r" in message or self._token in message:
            raise FeedWriteError("commit message was rejected", EXIT_USAGE)
        body: dict[str, str] = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        }
        if sha is not None:
            body["sha"] = sha
        encoded = json.dumps(body).encode("utf-8")
        status, _payload = self._call("PUT", self._url(path), encoded, json_body=True)
        if status in {200, 201}:
            return
        if status in {409, 422}:
            raise _Conflict()
        if status in {401, 403}:
            raise _auth_error(status)
        if status == 404:
            raise FeedWriteError(
                "repository or feed file was not found (HTTP 404). "
                "The token may lack access to this repository.",
                EXIT_NOT_FOUND,
            )
        raise FeedWriteError(f"GitHub contents write failed (HTTP {status})", EXIT_TRANSPORT)


def _commit(
    client: ContentsClient,
    bot: str,
    path: str,
    apply: Callable[[dict, datetime], tuple[bool, object, str]],
    moment: datetime,
    *,
    dry_run: bool,
    create: bool,
) -> tuple[object, str]:
    """Apply ``apply`` to a fresh file. Retry a conflict up to 3 times."""

    last_conflict = False
    for attempt in range(MAX_ATTEMPTS):
        doc, sha = client.read(path)
        if doc is None:
            if not create:
                raise FeedWriteError(f"feed file {path} was not found", EXIT_NOT_FOUND)
            doc = empty_feed(bot, moment)
            sha = None
        changed, payload, message = apply(doc, moment)
        validate_feed(doc, bot)
        text = dumps_feed(doc)
        if not changed or dry_run:
            return payload, text
        try:
            client.write(path, text, sha, message)
        except _Conflict:
            last_conflict = True
            if attempt + 1 >= MAX_ATTEMPTS:
                break
            continue
        return payload, text
    if last_conflict:
        raise FeedWriteError(
            "GitHub rejected the file sha after 3 retries",
            EXIT_CONFLICT,
        )
    raise FeedWriteError("GitHub contents write failed", EXIT_TRANSPORT)


def _print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feed_write",
        description="Edit feed/<bot>.json in a private data repo. Never writes desktop/.",
    )

    def error(message: str) -> None:
        if message.startswith("unrecognized arguments"):
            message = "unrecognized arguments"
        parser.exit(EXIT_USAGE, f"feed write failed: {message}\n")

    parser.error = error  # type: ignore[method-assign]
    parser.add_argument("--repo", help="GitHub repository as owner/name")
    parser.add_argument("--bot", help="bot id, default primary")
    parser.add_argument(
        "--token-env",
        default="TETHERBOT_FEED_TOKEN",
        help="environment variable that holds the token (default TETHERBOT_FEED_TOKEN)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resulting file without writing",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    add_todo = commands.add_parser("add-todo", help="append an open todo")
    add_todo.add_argument("--title", required=True)
    add_todo.add_argument("--body")
    add_todo.add_argument("--due", help="YYYY-MM-DD, YYYY-MM-DD HH:MM, or ISO 8601")
    add_todo.add_argument("--todo-kind", choices=("task", "bill"))
    add_todo.add_argument("--key", help="item id or bot/id; default <bot>-YYYYMMDD-NN")
    add_todo.add_argument("--tag", action="append", default=[], help="repeatable tag")
    add_todo.add_argument("--priority", type=int, choices=(1, 2, 3))
    add_todo.add_argument("--owner", choices=("user", "bot"))
    add_todo.add_argument("--waiting-on")
    add_todo.add_argument("--body-file", help="read the Markdown body from this path")
    add_todo.add_argument(
        "--markdown",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="store body_format markdown (default)",
    )

    add_ask = commands.add_parser("add-ask", help="append an open ask")
    add_ask.add_argument("--title", required=True)
    add_ask.add_argument("--body")

    close = commands.add_parser("close", help="mark an item done or dropped")
    close.add_argument("--key", required=True)
    close.add_argument("--status", choices=tuple(sorted(_CLOSE_STATUSES)), default="done")

    reopen = commands.add_parser("reopen", help="mark an item open")
    reopen.add_argument("--key", required=True)

    status = commands.add_parser("status", help="set the feed status block")
    status.add_argument("--state", required=True, choices=tuple(sorted(_STATES)))
    status.add_argument("--summary", required=True)
    status.add_argument("--next-run", help="ISO 8601 timestamp with an offset")
    status.add_argument("--last-run", help="ISO 8601 timestamp with an offset")

    listing = commands.add_parser("list", help="print items as JSON")
    listing.add_argument("--open", action="store_true", help="only status open")

    edit = commands.add_parser("edit", help="change one item")
    edit.add_argument("--key", required=True)
    edit.add_argument("--title")
    edit.add_argument("--body")
    edit.add_argument("--body-file")
    edit.add_argument("--due")
    edit.add_argument("--clear-due", action="store_true")
    edit.add_argument("--add-tag", action="append", default=[])
    edit.add_argument("--remove-tag", action="append", default=[])
    edit.add_argument("--priority", type=int, choices=(1, 2, 3))
    edit.add_argument("--waiting-on")
    edit.add_argument("--clear-waiting", action="store_true")
    edit.add_argument("--markdown", action=argparse.BooleanOptionalAction, default=None)

    paint = commands.add_parser("tag-color", help="set a tag palette color")
    paint.add_argument("--tag", required=True)
    paint.add_argument("--color", required=True, choices=tuple(sorted(_PALETTE)))
    return parser


def _command_body(args: argparse.Namespace) -> str | None:
    body_file = getattr(args, "body_file", None)
    body = getattr(args, "body", None)
    if body_file and body:
        raise FeedWriteError("pass body or body-file, not both", EXIT_USAGE)
    if body_file:
        return _read_body_file(body_file)
    return body


def main(
    argv: list[str] | None = None,
    *,
    request: Request | None = None,
    now: datetime | Callable[[], datetime] | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    """Run one subcommand. ``request`` replaces urllib in tests."""

    env = os.environ if environ is None else environ
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        repo = args.repo or env.get("TETHERBOT_FEED_REPO", "")
        bot = args.bot or env.get("TETHERBOT_FEED_BOT", "primary")
        repo = parse_repo(repo)
        path = feed_path(bot)
        token = _token_from_env(args.token_env, env)
        if request is None:
            request = _urlopen_request
        moment = _freeze(now)
        client = ContentsClient(repo, token, request)
        if args.command == "list":
            doc, _sha = client.read(path)
            if doc is None:
                raise FeedWriteError(f"feed file {path} was not found", EXIT_NOT_FOUND)
            validate_feed(doc, bot)
            _print_json(list_items(doc, bot, open_only=args.open))
            return EXIT_OK

        def apply(doc: dict, when: datetime) -> tuple[bool, object, str]:
            if args.command == "add-todo":
                return add_item(
                    doc,
                    bot=bot,
                    kind="todo",
                    title=args.title,
                    body=_command_body(args) or "",
                    moment=when,
                    actions=["done"],
                    key=args.key,
                    due=args.due,
                    todo_kind=args.todo_kind,
                    tags=args.tag,
                    priority=args.priority,
                    owner=args.owner or "user",
                    waiting_on=args.waiting_on,
                    markdown=bool(args.markdown),
                )
            if args.command == "add-ask":
                return add_item(
                    doc,
                    bot=bot,
                    kind="ask",
                    title=args.title,
                    body=args.body,
                    moment=when,
                    actions=["approve", "veto"],
                    key=None,
                    due=None,
                    todo_kind=None,
                )
            if args.command == "close":
                return set_item_status(
                    doc,
                    bot=bot,
                    key=args.key,
                    status=args.status,
                    moment=when,
                )
            if args.command == "reopen":
                return set_item_status(
                    doc,
                    bot=bot,
                    key=args.key,
                    status="open",
                    moment=when,
                )
            if args.command == "edit":
                return edit_item(
                    doc,
                    bot=bot,
                    key=args.key,
                    moment=when,
                    title=args.title,
                    body=_command_body(args),
                    due=args.due,
                    clear_due=args.clear_due,
                    add_tags=args.add_tag,
                    remove_tags=args.remove_tag,
                    priority=args.priority,
                    waiting_on=args.waiting_on,
                    clear_waiting=args.clear_waiting,
                    markdown=args.markdown,
                )
            if args.command == "tag-color":
                return set_tag_color(doc, tag=args.tag, color=args.color, moment=when)
            return set_feed_status(
                doc,
                state=args.state,
                summary=args.summary,
                moment=when,
                next_run=args.next_run,
                last_run=args.last_run,
            )

        create = args.command in {"add-todo", "add-ask", "status", "tag-color"}
        payload, text = _commit(
            client,
            bot,
            path,
            apply,
            moment,
            dry_run=args.dry_run,
            create=create,
        )
        if args.dry_run:
            sys.stdout.write(text)
        else:
            _print_json(payload)
        return EXIT_OK
    except FeedWriteError as exc:
        print(f"feed write failed: {exc}", file=sys.stderr)
        return exc.code


def _freeze(now: datetime | Callable[[], datetime] | None) -> datetime:
    if now is None:
        moment = datetime.now(UTC)
    elif isinstance(now, datetime):
        moment = now
    else:
        moment = now()
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise FeedWriteError("clock must be timezone-aware", EXIT_USAGE)
    return moment


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow a redirect. The Authorization header would travel with it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> tuple[int, object, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


if __name__ == "__main__":
    sys.exit(main())

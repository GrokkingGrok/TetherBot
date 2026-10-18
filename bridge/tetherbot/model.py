# SPDX-License-Identifier: GPL-2.0-or-later
"""Item and action-envelope models.

Field rules live in docs/PROTOCOL.md. Unknown fields are kept on ``extra``
and are not first-class attributes. The secret guard replaces a whole
sensitive field before the item is stored. Log lines mask the matching
span and leave the rest of the line in place.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

SECRET_REPLACEMENT = "[redacted: looked like a secret]"

KNOWN_KINDS = frozenset({"ask", "todo", "watch", "notification", "status"})
ITEM_ACTIONS = frozenset({"approve", "veto", "done", "snooze", "open_chat"})
ENVELOPE_ACTIONS = frozenset({"approve", "veto", "done", "reopen", "run_now", "note"})
ITEM_STATUSES = frozenset({"open", "done", "dropped", "expired"})

_ID = re.compile(r"^[a-z0-9-]{3,64}$")
_BOT = re.compile(r"^[a-z0-9-]{1,64}$")
_DUE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DUE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_PREFIX = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(?:ghp_|github_pat_|sk-|AKIA)")
_TOKEN = re.compile(
    r"(?:^|(?<=[^A-Za-z0-9]))(?:ghp_|github_pat_|sk-|AKIA)[A-Za-z0-9_\-]*"
)
_DIGITS = re.compile(r"\d{9,}")
_HEX = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")
_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_AUTHORIZATION = re.compile(r"(?i)\bAuthorization:\s*\S+")

_KNOWN_FIELDS = frozenset(
    {
        "id",
        "kind",
        "title",
        "body",
        "status",
        "created",
        "updated_at",
        "priority",
        "due",
        "owner",
        "waiting",
        "estimate_min",
        "todo_kind",
        "amount",
        "actions",
        "notify",
        "expires_at",
        "source",
        "links",
    }
)


def looks_like_secret(text: str, extra: Sequence[str] = ()) -> bool:
    """Return whether ``text`` matches the protocol secret guard."""

    if _PREFIX.search(text) or _DIGITS.search(text):
        return True
    if _HEX.search(text) or _B64.search(text):
        return True
    return any(secret and secret in text for secret in extra)


def redact_field(text: str, extra: Sequence[str] = ()) -> str:
    """Replace a whole item field when any part looks like a secret."""

    if looks_like_secret(text, extra):
        return SECRET_REPLACEMENT
    return text


def mask_secrets(text: str, extra: Sequence[str] = ()) -> str:
    """Mask secret-shaped spans inside a log line."""

    masked = _TOKEN.sub(SECRET_REPLACEMENT, text)
    masked = _BEARER.sub("Bearer " + SECRET_REPLACEMENT, masked)
    masked = _AUTHORIZATION.sub("Authorization: " + SECRET_REPLACEMENT, masked)
    masked = _B64.sub(SECRET_REPLACEMENT, masked)
    masked = _HEX.sub(SECRET_REPLACEMENT, masked)
    masked = _DIGITS.sub(SECRET_REPLACEMENT, masked)
    for secret in extra:
        if secret:
            masked = masked.replace(secret, SECRET_REPLACEMENT)
    return masked


def global_key(bot: str, item_id: str) -> str:
    """Return the in-bridge key ``<bot>/<id>``."""

    return f"{bot}/{item_id}"


def parse_iso8601(value: object, *, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp that includes an offset."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp with an offset")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp with an offset") from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


@dataclass
class Item:
    id: str
    kind: str
    title: str
    bot: str
    created: str
    updated_at: str
    source: dict[str, str]
    status: str = "open"
    body: str = ""
    origin: str = ""
    priority: int | None = None
    due: str | None = None
    owner: str | None = None
    waiting: dict[str, str] | None = None
    estimate_min: int | None = None
    todo_kind: str | None = None
    amount: str | None = None
    actions: list[str] = field(default_factory=list)
    notify: bool = False
    expires_at: str | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    snoozed_until: str | None = None
    seen: bool = False
    done_locally: bool = False
    acted: dict[str, str] | None = None
    resolved: str | None = None
    redacted_fields: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return global_key(self.bot, self.id)

    @property
    def actionable(self) -> bool:
        """Unknown kinds stay in the store and never grow action buttons."""

        return self.kind in KNOWN_KINDS and self.status == "open" and bool(self.actions)

    def clone(self) -> Item:
        return replace(
            self,
            source=dict(self.source),
            waiting=None if self.waiting is None else dict(self.waiting),
            actions=list(self.actions),
            links=[dict(link) for link in self.links],
            extra=dict(self.extra),
            acted=None if self.acted is None else dict(self.acted),
            redacted_fields=tuple(self.redacted_fields),
        )

    def protocol_dict(self) -> dict[str, Any]:
        """Feed fields plus unknown extras. Local snooze state is not included."""

        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "created": self.created,
            "updated_at": self.updated_at,
            "priority": self.priority,
            "due": self.due,
            "owner": self.owner,
            "waiting": None if self.waiting is None else dict(self.waiting),
            "estimate_min": self.estimate_min,
            "todo_kind": self.todo_kind,
            "amount": self.amount,
            "actions": list(self.actions),
            "notify": self.notify,
            "expires_at": self.expires_at,
            "source": dict(self.source),
            "links": [dict(link) for link in self.links],
            "extra": dict(self.extra),
        }

    def to_cache(self) -> dict[str, Any]:
        payload = self.protocol_dict()
        payload["origin"] = self.origin
        local: dict[str, Any] = {
            "snoozed_until": self.snoozed_until,
            "seen": self.seen,
            "done_locally": self.done_locally,
        }
        if self.acted is not None:
            local["acted"] = dict(self.acted)
        if self.resolved is not None:
            local["resolved"] = self.resolved
        payload["local"] = local
        payload["redacted_fields"] = list(self.redacted_fields)
        return payload

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, bot: str, origin: str) -> Item:
        """Validate one feed item and apply the secret guard."""

        if not isinstance(data, Mapping):
            raise TypeError("item must be an object")
        if not isinstance(bot, str) or _BOT.fullmatch(bot) is None:
            raise ValueError("bot id must match [a-z0-9-]{1,64}")
        item_id = _require_id(data.get("id"))
        kind = _require_text(data.get("kind"), "kind")
        title = _require_title(data.get("title"))
        body = _optional_body(data.get("body", ""))
        status = _require_status(data.get("status", "open"))
        created = _require_timestamp(data.get("created"), "created")
        updated_at = _require_timestamp(data.get("updated_at"), "updated_at")
        priority = _optional_int(data.get("priority"), "priority", 1, 3)
        due = _optional_due(data.get("due"))
        owner = _optional_short(data.get("owner"), "owner", 64)
        waiting = _optional_waiting(data.get("waiting"))
        estimate_min = _optional_int(data.get("estimate_min"), "estimate_min", 1, 480)
        todo_kind = _optional_todo_kind(data.get("todo_kind"), kind)
        amount = _optional_amount(data.get("amount"), kind, todo_kind)
        actions = _optional_actions(data.get("actions"))
        notify = _optional_bool(data.get("notify", False), "notify")
        expires_at = _optional_timestamp(data.get("expires_at"), "expires_at")
        source = _require_source(data.get("source"), bot)
        links = _optional_links(data.get("links"))
        extra = {key: value for key, value in data.items() if key not in _KNOWN_FIELDS}
        redacted: list[str] = []
        title, body, amount, waiting = _guard_secrets(
            title, body, amount, waiting, redacted
        )
        if redacted:
            logging.getLogger("tetherbot").info(
                "redacted %s on %s",
                ",".join(redacted),
                global_key(bot, item_id),
            )
        return cls(
            id=item_id,
            kind=kind,
            title=title,
            bot=bot,
            created=created,
            updated_at=updated_at,
            source=source,
            status=status,
            body=body,
            origin=origin,
            priority=priority,
            due=due,
            owner=owner,
            waiting=waiting,
            estimate_min=estimate_min,
            todo_kind=todo_kind,
            amount=amount,
            actions=actions,
            notify=notify,
            expires_at=expires_at,
            links=links,
            extra=extra,
            redacted_fields=tuple(redacted),
        )

    @classmethod
    def from_cache(cls, data: Mapping[str, Any]) -> Item:
        if not isinstance(data, Mapping):
            raise TypeError("cached item must be an object")
        origin = data.get("origin")
        if not isinstance(origin, str) or not origin:
            raise ValueError("cached item origin is required")
        local = data.get("local", {})
        if not isinstance(local, Mapping):
            raise ValueError("cached item local state must be an object")
        extras = data.get("extra", {})
        if not isinstance(extras, dict):
            raise ValueError("cached item extra must be an object")
        feed = {
            key: value
            for key, value in data.items()
            if key not in {"origin", "local", "redacted_fields", "extra"}
        }
        feed.update(extras)
        bot = feed.get("source", {}).get("bot") if isinstance(feed.get("source"), Mapping) else None
        if not isinstance(bot, str):
            raise ValueError("cached item source.bot is required")
        item = cls.from_mapping(feed, bot=bot, origin=origin)
        snoozed = local.get("snoozed_until")
        if snoozed is not None:
            parse_iso8601(snoozed, field_name="snoozed_until")
            if not isinstance(snoozed, str):
                raise ValueError("snoozed_until must be a string")
        seen = local.get("seen", False)
        done = local.get("done_locally", False)
        if not isinstance(seen, bool) or not isinstance(done, bool):
            raise ValueError("cached local flags must be booleans")
        item.snoozed_until = snoozed if isinstance(snoozed, str) else None
        item.seen = seen
        item.done_locally = done
        item.acted = parse_acted(local.get("acted"))
        resolved = local.get("resolved")
        item.resolved = resolved if resolved in {"done", "dropped"} else None
        return item


def parse_acted(value: object) -> dict[str, str] | None:
    """Return a local action record, or None when the value is absent or unusable.

    The record is ``action``, ``action_id``, and ``at``. A bad value is
    ignored so an older or partial file does not make the cache unreadable.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        return None
    action = value.get("action")
    action_id = value.get("action_id")
    at = value.get("at")
    if action not in {"approve", "veto", "done"}:
        return None
    if not isinstance(action_id, str) or not action_id or looks_like_secret(action_id):
        return None
    if not isinstance(at, str):
        return None
    try:
        parse_iso8601(at, field_name="at")
    except ValueError:
        return None
    return {"action": action, "action_id": action_id, "at": at}


def resolved_status(action: str) -> str | None:
    """Feed status that mirrors one closing action. Approve and done are ``done``."""

    if action in {"approve", "done"}:
        return "done"
    if action == "veto":
        return "dropped"
    return None


def _guard_secrets(
    title: str,
    body: str,
    amount: str | None,
    waiting: dict[str, str] | None,
    redacted: list[str],
) -> tuple[str, str, str | None, dict[str, str] | None]:
    if looks_like_secret(title):
        title = SECRET_REPLACEMENT
        redacted.append("title")
    if looks_like_secret(body):
        body = SECRET_REPLACEMENT
        redacted.append("body")
    if amount is not None and looks_like_secret(amount):
        amount = SECRET_REPLACEMENT
        redacted.append("amount")
    if waiting is not None and "on" in waiting and looks_like_secret(waiting["on"]):
        waiting = dict(waiting)
        waiting["on"] = SECRET_REPLACEMENT
        redacted.append("waiting.on")
    return title, body, amount, waiting


def _require_id(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError("item id must match [a-z0-9-]{3,64}")
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _require_title(value: object) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise ValueError("title must be a single line")
    if not 1 <= len(value) <= 120:
        raise ValueError("title must be 1 to 120 characters")
    return value


def _optional_body(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("body must be a string")
    if len(value) > 1000:
        raise ValueError("body must be at most 1000 characters")
    return value


def _require_status(value: object) -> str:
    if not isinstance(value, str) or value not in ITEM_STATUSES:
        raise ValueError("status must be open, done, dropped, or expired")
    return value


def _require_timestamp(value: object, field_name: str) -> str:
    parse_iso8601(value, field_name=field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _optional_timestamp(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_timestamp(value, field_name)


def _optional_int(value: object, field_name: str, low: int, high: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{field_name} must be an integer from {low} to {high}")
    return value


def _optional_due(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("due must be a string")
    if _DUE_DATE.fullmatch(value):
        datetime.strptime(value, "%Y-%m-%d")
        return value
    if _DUE_TIME.fullmatch(value):
        datetime.strptime(value, "%Y-%m-%d %H:%M")
        return value
    raise ValueError("due must be YYYY-MM-DD or YYYY-MM-DD HH:MM")


def _optional_short(value: object, field_name: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field_name} must be 1 to {limit} characters")
    return value


def _optional_waiting(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("waiting must be an object")
    parsed: dict[str, str] = {}
    on = value.get("on")
    if on is not None:
        if not isinstance(on, str) or len(on) > 40:
            raise ValueError("waiting.on must be a string of at most 40 characters")
        parsed["on"] = on
    check_back = value.get("check_back")
    if check_back is not None:
        if not isinstance(check_back, str) or _DUE_DATE.fullmatch(check_back) is None:
            raise ValueError("waiting.check_back must be YYYY-MM-DD")
        datetime.strptime(check_back, "%Y-%m-%d")
        parsed["check_back"] = check_back
    return parsed or None


def _optional_todo_kind(value: object, kind: str) -> str | None:
    if value is None:
        return None
    if kind != "todo":
        raise ValueError("todo_kind is only valid on todo items")
    if value not in {"task", "bill"}:
        raise ValueError("todo_kind must be task or bill")
    return value


def _optional_amount(value: object, kind: str, todo_kind: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 20:
        raise ValueError("amount must be 1 to 20 characters")
    bill = kind == "todo" and todo_kind == "bill"
    if kind != "watch" and not bill:
        raise ValueError("amount is only valid on bills and watch items")
    return value


def _optional_actions(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise ValueError("actions must be a list of strings")
    if any(entry not in ITEM_ACTIONS for entry in value):
        raise ValueError("actions must be a subset of the protocol actions")
    return list(value)


def _optional_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_source(value: object, bot: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("source is required")
    if value.get("bot") != bot:
        raise ValueError("source.bot must match the feed bot")
    source = {"bot": bot}
    routine = value.get("routine")
    if routine is not None:
        if not isinstance(routine, str) or not routine:
            raise ValueError("source.routine must be a string")
        source["routine"] = routine
    return source


def _optional_links(value: object) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("links must be a list")
    if len(value) > 3:
        raise ValueError("links has a maximum of 3")
    parsed: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise ValueError("link must be an object")
        label = entry.get("label")
        url = entry.get("url")
        if not isinstance(label, str) or not label:
            raise ValueError("link label is required")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("link url must be https")
        parsed.append({"label": label, "url": url})
    return parsed


@dataclass
class ActionEnvelope:
    """Desktop-to-bot batch. The webhook key never belongs in this body."""

    schema: str
    type: str
    batch_id: str
    sent_at: str
    actions: list[dict[str, Any]]
    client: dict[str, Any] = field(default_factory=dict)

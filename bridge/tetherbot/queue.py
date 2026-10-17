# SPDX-License-Identifier: GPL-2.0-or-later
"""On-disk outbound action queue.

Each action is one mode-0600 JSON file, fsynced before ``enqueue`` returns.
A new ``ActionQueue`` on the same directory resumes that set. Actions for
one bot leave as a single batch after a quiet period (default 20 seconds)
and never wait longer than 120 seconds from the oldest action. Pace is one
POST per bot per 60 seconds and 30 posts per UTC day. Over budget, the
files stay pending.

The daily cap uses UTC dates. ``mark_attempt`` is one POST, not one action.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tetherbot import SCHEMA_VERSION
from tetherbot.files import ensure_private_dir, write_private_json
from tetherbot.model import ENVELOPE_ACTIONS, looks_like_secret, parse_iso8601
from tetherbot.version_gate import check_schema

DEFAULT_COALESCE_SECONDS = 20
DEFAULT_COALESCE_MAX_SECONDS = 120
DEFAULT_MIN_INTERVAL_SECONDS = 60
DEFAULT_DAILY_CAP = 30

_ACTION_ID = re.compile(r"^[a-z0-9-]{3,64}$")
_BOT = re.compile(r"^[a-z0-9-]{1,64}$")


class QueueError(ValueError):
    """The action was refused and nothing was written."""


@dataclass
class QueuedAction:
    action_id: str
    bot: str
    item: str
    action: str
    args: dict[str, Any]
    created: str
    state: str = "pending"
    attempts: int = 0
    detail: str = ""

    def clone(self) -> QueuedAction:
        return replace(self, args=dict(self.args))


@dataclass
class RoutePace:
    last_send: datetime | None = None
    sent_on: str | None = None
    sent_count: int = 0


class ActionQueue:
    def __init__(
        self,
        directory: Path,
        *,
        coalesce_seconds: int = DEFAULT_COALESCE_SECONDS,
        coalesce_max_seconds: int = DEFAULT_COALESCE_MAX_SECONDS,
        min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS,
        daily_cap: int = DEFAULT_DAILY_CAP,
    ) -> None:
        _check_limits(
            coalesce_seconds,
            coalesce_max_seconds,
            min_interval_seconds,
            daily_cap,
        )
        self.directory = directory
        self.coalesce_seconds = coalesce_seconds
        self.coalesce_max_seconds = coalesce_max_seconds
        self.min_interval_seconds = min_interval_seconds
        self.daily_cap = daily_cap
        self.errors: list[str] = []
        self._actions: dict[str, QueuedAction] = {}
        self._routes: dict[str, RoutePace] = {}
        ensure_private_dir(directory)
        self._load()

    def enqueue(
        self,
        *,
        bot: str,
        item: str,
        action: str,
        created: str,
        args: dict[str, Any] | None = None,
        action_id: str | None = None,
    ) -> str:
        payload_args = {} if args is None else dict(args)
        chosen = action_id or f"a-{secrets.token_hex(4)}"
        _validate_action(chosen, bot, item, action, payload_args, created)
        if chosen in self._actions or (self.directory / f"{chosen}.json").exists():
            raise QueueError("action_id already exists")
        queued = QueuedAction(
            action_id=chosen,
            bot=bot,
            item=item,
            action=action,
            args=payload_args,
            created=created,
        )
        self._write_action(queued)
        self._actions[chosen] = queued
        return chosen

    def next_batch(self, now: datetime) -> tuple[QueuedAction, ...] | None:
        """Return one bot's due batch. The files stay pending until accept or park."""

        moment = _as_utc(now)
        for bot in sorted({action.bot for action in self._actions.values()}):
            pending = [
                action
                for action in self._actions.values()
                if action.bot == bot and action.state == "pending"
            ]
            if not pending or not _coalesce_ready(pending, moment, self):
                continue
            route = self._routes.get(bot)
            if route is not None and not _pace_ready(route, moment, self):
                continue
            return tuple(action.clone() for action in sorted(pending, key=lambda row: row.created))
        return None

    def pending_count(self) -> int:
        """Pending outbound actions. Parked actions are not included."""

        return sum(action.state == "pending" for action in self._actions.values())

    def mark_attempt(self, bot: str, action_ids: list[str], *, now: datetime) -> None:
        """Record one POST for ``bot``. Each listed action gains one attempt."""

        moment = _as_utc(now)
        if not action_ids:
            raise QueueError("mark_attempt needs the action ids that were posted")
        for action_id in action_ids:
            action = self._actions.get(action_id)
            if action is None or action.bot != bot:
                raise QueueError("mark_attempt action is not queued for that bot")
            action.attempts += 1
            self._write_action(action)
        route = self._routes.setdefault(bot, RoutePace())
        day = moment.date().isoformat()
        if route.sent_on != day:
            route.sent_on = day
            route.sent_count = 0
        route.sent_count += 1
        route.last_send = moment
        self._write_meta()

    def accept(self, action_ids: list[str]) -> None:
        for action_id in action_ids:
            self._discard(action_id)

    def park(self, action_id: str, detail: str) -> None:
        action = self._require(action_id)
        action.state = "parked"
        action.detail = detail
        self._write_action(action)

    def drop(self, action_id: str) -> None:
        self._discard(action_id)

    def retry(self, action_id: str) -> None:
        action = self._require(action_id)
        action.state = "pending"
        action.detail = ""
        self._write_action(action)

    def _require(self, action_id: str) -> QueuedAction:
        action = self._actions.get(action_id)
        if action is None:
            raise QueueError("action is not in the queue")
        return action

    def _discard(self, action_id: str) -> None:
        self._require(action_id)
        path = self.directory / f"{action_id}.json"
        path.unlink(missing_ok=True)
        self._actions.pop(action_id, None)

    def _write_action(self, action: QueuedAction) -> None:
        payload = {
            "schema": SCHEMA_VERSION,
            "action_id": action.action_id,
            "bot": action.bot,
            "item": action.item,
            "action": action.action,
            "args": action.args,
            "created": action.created,
            "state": action.state,
            "attempts": action.attempts,
            "detail": action.detail,
        }
        write_private_json(self.directory / f"{action.action_id}.json", payload)

    def _write_meta(self) -> None:
        routes = {
            bot: {
                "last_send": None if pace.last_send is None else pace.last_send.isoformat(),
                "sent_on": pace.sent_on,
                "sent_count": pace.sent_count,
            }
            for bot, pace in sorted(self._routes.items())
        }
        write_private_json(
            self.directory / "meta.json",
            {"schema": SCHEMA_VERSION, "routes": routes},
        )

    def _load(self) -> None:
        meta_path = self.directory / "meta.json"
        if meta_path.exists():
            self._load_meta(meta_path)
        for path in sorted(self.directory.glob("*.json")):
            if path.name == "meta.json":
                continue
            self._load_action(path)

    def _load_meta(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            decision = check_schema(raw.get("schema"), source=path.name)
            if not decision.accepted:
                raise ValueError(decision.message)
            routes = raw["routes"]
            if not isinstance(routes, dict):
                raise ValueError("routes must be an object")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.errors.append(f"{path.name}: {exc}")
            return
        for bot, pace in routes.items():
            if not isinstance(pace, dict):
                self.errors.append(f"{path.name}: bad route {bot}")
                continue
            last = pace.get("last_send")
            parsed = None if last is None else parse_iso8601(last, field_name="last_send")
            self._routes[str(bot)] = RoutePace(
                last_send=None if parsed is None else parsed.astimezone(UTC),
                sent_on=pace.get("sent_on"),
                sent_count=int(pace.get("sent_count", 0)),
            )

    def _load_action(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            decision = check_schema(raw.get("schema"), source=path.name)
            if not decision.accepted:
                raise ValueError(decision.message)
            action = QueuedAction(
                action_id=raw["action_id"],
                bot=raw["bot"],
                item=raw["item"],
                action=raw["action"],
                args=dict(raw.get("args", {})),
                created=raw["created"],
                state=raw.get("state", "pending"),
                attempts=int(raw.get("attempts", 0)),
                detail=str(raw.get("detail", "")),
            )
            _validate_action(
                action.action_id,
                action.bot,
                action.item,
                action.action,
                action.args,
                action.created,
            )
            if action.state not in {"pending", "parked"}:
                raise ValueError("state must be pending or parked")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.errors.append(f"{path.name}: {exc}")
            return
        self._actions[action.action_id] = action


def _check_limits(
    coalesce_seconds: int,
    coalesce_max_seconds: int,
    min_interval_seconds: int,
    daily_cap: int,
) -> None:
    if coalesce_seconds < 1 or coalesce_max_seconds < coalesce_seconds:
        raise ValueError("coalesce window is invalid")
    if coalesce_max_seconds > DEFAULT_COALESCE_MAX_SECONDS:
        raise ValueError("coalesce max cannot exceed 120 seconds")
    if min_interval_seconds < 1 or daily_cap < 1:
        raise ValueError("pace limits must be at least 1")


def _validate_action(
    action_id: str,
    bot: str,
    item: str,
    action: str,
    args: dict[str, Any],
    created: str,
) -> None:
    if action_id == "meta" or _ACTION_ID.fullmatch(action_id) is None:
        raise QueueError("action_id must match [a-z0-9-]{3,64} and not be meta")
    if _BOT.fullmatch(bot) is None:
        raise QueueError("bot id must match [a-z0-9-]{1,64}")
    if action not in ENVELOPE_ACTIONS:
        raise QueueError("action is not in the protocol set")
    if not item.startswith(f"{bot}/"):
        raise QueueError("item key must start with the bot id")
    parse_iso8601(created, field_name="created")
    if action == "note":
        text = args.get("text")
        if not isinstance(text, str) or not text or len(text) > 500:
            raise QueueError("note text must be 1 to 500 characters")
    elif args:
        raise QueueError("only note actions carry args")
    if _strings_look_secret(item) or _strings_look_secret(action) or _tree_looks_secret(args):
        raise QueueError("refusing to queue an action that looks like a secret")


def _strings_look_secret(value: str) -> bool:
    return looks_like_secret(value)


def _tree_looks_secret(value: object) -> bool:
    if isinstance(value, str):
        return looks_like_secret(value)
    if isinstance(value, dict):
        return any(
            _tree_looks_secret(key) or _tree_looks_secret(child) for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_tree_looks_secret(child) for child in value)
    return False


def _coalesce_ready(pending: list[QueuedAction], now: datetime, queue: ActionQueue) -> bool:
    created = [
        parse_iso8601(action.created, field_name="created").astimezone(UTC) for action in pending
    ]
    oldest, newest = min(created), max(created)
    quiet = newest + timedelta(seconds=queue.coalesce_seconds)
    ceiling = oldest + timedelta(seconds=queue.coalesce_max_seconds)
    return now >= quiet or now >= ceiling


def _pace_ready(route: RoutePace, now: datetime, queue: ActionQueue) -> bool:
    if route.last_send is not None:
        earliest = route.last_send + timedelta(seconds=queue.min_interval_seconds)
        if now < earliest:
            return False
    if route.sent_on == now.date().isoformat() and route.sent_count >= queue.daily_cap:
        return False
    return True


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("timestamps must include a timezone offset")
    return now.astimezone(UTC)


def queue_file_mode(path: Path) -> int:
    """Return the permission bits for tests and diagnostics."""

    return os.stat(path).st_mode & 0o777

# SPDX-License-Identifier: GPL-2.0-or-later
"""Item store, diff, and local expiry.

``replace_origin`` is the successful-read path. A failed read must not call
it with an empty list, or that origin's items would be removed. A snooze
and ``expires_at`` are applied locally. Notifications come from
``notify_policy``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tetherbot import SCHEMA_VERSION
from tetherbot.files import write_private_json
from tetherbot.model import Item, parse_iso8601
from tetherbot.notify_policy import Notice, NotifyPolicy
from tetherbot.version_gate import check_schema


@dataclass(frozen=True)
class Diff:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class Notification:
    reason: str
    item: Item


@dataclass(frozen=True)
class StoreUpdate:
    diff: Diff
    notifications: tuple[Notification, ...]
    errors: tuple[str, ...]


class ItemStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.load_error: str | None = None
        self._items: dict[str, Item] = {}
        self._policy = NotifyPolicy()
        self._block_save = False
        if path is not None and path.exists():
            self._load()

    def items(self) -> tuple[Item, ...]:
        return tuple(self._items[key].clone() for key in sorted(self._items))

    def get(self, key: str) -> Item | None:
        item = self._items.get(key)
        return None if item is None else item.clone()

    def counts(self, *, now: datetime) -> dict[str, int]:
        _require_aware(now)
        visible = [
            item
            for item in self._items.values()
            if item.status == "open" and not _snoozed(item, now)
        ]
        return {
            "asks": sum(item.kind == "ask" for item in visible),
            "todos": sum(item.kind == "todo" for item in visible),
            "watch": sum(item.kind == "watch" for item in visible),
            "notifications": sum(item.kind == "notification" for item in visible),
            "waiting": sum(item.waiting is not None for item in visible),
        }

    def replace_origin(
        self,
        origin: str,
        items: list[Item],
        *,
        now: datetime,
    ) -> StoreUpdate:
        """Replace every item previously stored for ``origin``."""

        _require_aware(now)
        if not origin:
            raise ValueError("origin is required")
        self._block_save = False
        before = _snapshot(self._items)
        errors = self._merge_origin(origin, items)
        self._apply_local(now)
        update = self._diff_and_notify(before, now)
        if errors:
            update = StoreUpdate(update.diff, update.notifications, tuple(errors))
        self._save()
        return update

    def refresh(self, now: datetime) -> StoreUpdate:
        """Apply snooze expiry and ``expires_at`` without changing the feed."""

        _require_aware(now)
        before = _snapshot(self._items)
        self._apply_local(now)
        update = self._diff_and_notify(before, now)
        if update.diff.updated or update.notifications:
            self._save()
        return update

    def snooze(self, key: str, until: datetime, *, now: datetime) -> bool:
        _require_aware(now)
        _require_aware(until)
        item = self._items.get(key)
        if item is None or until <= now:
            return False
        item.snoozed_until = until.astimezone(now.tzinfo).isoformat()
        self._save()
        return True

    def mark_seen(self, keys: list[str]) -> None:
        changed = False
        for key in keys:
            item = self._items.get(key)
            if item is not None and not item.seen:
                item.seen = True
                changed = True
        if changed:
            self._save()

    def _merge_origin(self, origin: str, items: list[Item]) -> list[str]:
        errors: list[str] = []
        incoming: dict[str, Item] = {}
        for item in items:
            if item.origin != origin:
                errors.append(f"{item.key}: origin does not match {origin}")
                continue
            if item.key in incoming:
                errors.append(f"{item.key}: duplicate key")
                continue
            incoming[item.key] = item.clone()
        for key, item in list(self._items.items()):
            if item.origin == origin and key not in incoming:
                del self._items[key]
        for key, item in incoming.items():
            existing = self._items.get(key)
            if existing is not None and existing.origin != origin:
                errors.append(f"{key}: already owned by {existing.origin}")
                continue
            if existing is not None:
                item.snoozed_until = existing.snoozed_until
                item.seen = existing.seen
                item.done_locally = existing.done_locally
            self._items[key] = item
        return errors

    def _apply_local(self, now: datetime) -> None:
        for item in self._items.values():
            if item.expires_at and item.status == "open":
                expires = parse_iso8601(item.expires_at, field_name="expires_at")
                if now >= expires:
                    item.status = "expired"
            if item.snoozed_until:
                until = parse_iso8601(item.snoozed_until, field_name="snoozed_until")
                if now >= until:
                    item.snoozed_until = None

    def _diff_and_notify(
        self,
        before: dict[str, tuple[str, str, str | None]],
        now: datetime,
    ) -> StoreUpdate:
        after = _snapshot(self._items)
        added = tuple(sorted(key for key in after if key not in before))
        removed = tuple(sorted(key for key in before if key not in after))
        updated = tuple(
            sorted(key for key in after if key in before and after[key] != before[key])
        )
        notices: list[Notice] = []
        for key, item in self._items.items():
            notices.extend(
                self._policy.consider(item, now=now, seen_before=key in before)
            )
        self._policy.mark(notices)
        notifications = tuple(
            Notification(reason=notice.reason, item=self._items[notice.key].clone())
            for notice in notices
            if notice.key in self._items
        )
        return StoreUpdate(Diff(added, updated, removed), notifications, ())

    def _load(self) -> None:
        assert self.path is not None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.load_error = f"items cache unreadable ({exc.__class__.__name__})"
            self._block_save = True
            return
        if not isinstance(raw, dict):
            self.load_error = "items cache invalid (type)"
            self._block_save = True
            return
        decision = check_schema(raw.get("schema"), source=self.path.name)
        if not decision.accepted:
            self.load_error = decision.message
            self._block_save = True
            return
        try:
            items = [Item.from_cache(entry) for entry in raw["items"]]
            delivered = {
                (str(token[0]), str(token[1]), str(token[2]))
                for token in raw.get("delivered", [])
            }
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            self.load_error = f"items cache invalid ({exc.__class__.__name__})"
            self._block_save = True
            return
        self._items = {item.key: item for item in items}
        self._policy = NotifyPolicy(delivered)

    def _save(self) -> None:
        if self.path is None or self._block_save:
            return
        payload = {
            "schema": SCHEMA_VERSION,
            "items": [item.to_cache() for item in self.items()],
            "delivered": [list(token) for token in sorted(self._policy.delivered)],
        }
        write_private_json(self.path, payload)


def _snapshot(items: dict[str, Item]) -> dict[str, tuple[str, str, str | None]]:
    return {
        key: (item.origin, _fingerprint(item), item.snoozed_until)
        for key, item in items.items()
    }


def _fingerprint(item: Item) -> str:
    return json.dumps(item.protocol_dict(), sort_keys=True, separators=(",", ":"))


def _snoozed(item: Item, now: datetime) -> bool:
    if not item.snoozed_until:
        return False
    return parse_iso8601(item.snoozed_until, field_name="snoozed_until") > now


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError("timestamps must include a timezone offset")

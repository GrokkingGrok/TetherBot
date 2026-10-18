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
from tetherbot.model import Item, parse_acted, parse_iso8601, resolved_status
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
        self.repo_state_dirty = False
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
            if _listed(item, now)
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

    def record_action(self, key: str, action: str, action_id: str, at: datetime) -> bool:
        """Hide ``key`` while approve, veto, or done is queued.

        The feed status stays as the bot wrote it. ``at`` is the tap time
        a later feed edit is compared with.
        """

        _require_aware(at)
        if resolved_status(action) is None:
            return False
        item = self._items.get(key)
        acted = parse_acted({"action": action, "action_id": action_id, "at": at.isoformat()})
        if item is None or acted is None:
            return False
        item.acted = acted
        item.resolved = None
        self.repo_state_dirty = True
        self._save()
        return True

    def resolve_batch(self, actions: list[object]) -> list[str]:
        """Mark the last closing action for each item resolved. Feed files stay untouched."""

        last: dict[str, tuple[str, str, str]] = {}
        for action in actions:
            name = getattr(action, "action", "")
            item_key = getattr(action, "item", "")
            action_id = getattr(action, "action_id", "")
            created = getattr(action, "created", "")
            if resolved_status(name) is None or not isinstance(item_key, str):
                continue
            if not isinstance(action_id, str) or not isinstance(created, str):
                continue
            last[item_key] = (name, action_id, created)
        changed: list[str] = []
        for item_key, (name, action_id, created) in last.items():
            item = self._items.get(item_key)
            if item is None:
                continue
            at = created
            if item.acted is not None and item.acted.get("action_id") == action_id:
                at = item.acted["at"]
            acted = parse_acted({"action": name, "action_id": action_id, "at": at})
            if acted is None:
                continue
            item.acted = acted
            item.resolved = resolved_status(name)
            changed.append(item_key)
        if changed:
            self.repo_state_dirty = True
            self._save()
        return changed

    def release_actions(self, action_ids: list[str]) -> list[str]:
        """Show items again when their closing action was parked, rejected, or dropped."""

        ids = set(action_ids)
        changed: list[str] = []
        for item in self._items.values():
            if item.acted is None or item.acted.get("action_id") not in ids:
                continue
            item.acted = None
            item.resolved = None
            changed.append(item.key)
        if changed:
            self.repo_state_dirty = True
            self._save()
        return changed

    def apply_repo_state(self, entries: list[object]) -> list[str]:
        """Copy closing marks from ``desktop/state.json``. Snooze stays on this machine."""

        changed: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            item = self._items.get(key) if isinstance(key, str) else None
            if item is None:
                continue
            acted = parse_acted(entry.get("acted"))
            if acted is None or not _state_mark_applies(item, acted):
                continue
            status = entry.get("status")
            resolved = status if status in {"done", "dropped"} else None
            if item.acted == acted and item.resolved == resolved:
                continue
            item.acted = acted
            item.resolved = resolved
            changed.append(item.key)
        if changed:
            self._save()
        return changed

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
                if _feed_replaces_local_close(item, existing):
                    if existing.acted or existing.resolved:
                        self.repo_state_dirty = True
                else:
                    item.acted = None if existing.acted is None else dict(existing.acted)
                    item.resolved = existing.resolved
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
        self.repo_state_dirty = any(item.acted or item.resolved for item in items)

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


def _listed(item: Item, now: datetime) -> bool:
    if item.status != "open" or item.acted or item.resolved:
        return False
    return not _snoozed(item, now)


def _feed_replaces_local_close(incoming: Item, existing: Item) -> bool:
    """True when the feed, not the desktop tap, should decide visibility."""

    if not existing.acted and not existing.resolved:
        return True
    if incoming.status in {"done", "dropped", "expired"}:
        return True
    acted_at = None if existing.acted is None else existing.acted.get("at")
    if incoming.status == "open" and isinstance(acted_at, str):
        try:
            return parse_iso8601(incoming.updated_at, field_name="updated_at") > parse_iso8601(
                acted_at, field_name="at"
            )
        except ValueError:
            return False
    return False


def _state_mark_applies(item: Item, acted: dict[str, str]) -> bool:
    if item.status in {"done", "dropped", "expired"}:
        return False
    try:
        feed_at = parse_iso8601(item.updated_at, field_name="updated_at")
        acted_at = parse_iso8601(acted["at"], field_name="at")
    except ValueError:
        return False
    return item.status != "open" or feed_at <= acted_at


def _snoozed(item: Item, now: datetime) -> bool:
    if not item.snoozed_until:
        return False
    return parse_iso8601(item.snoozed_until, field_name="snoozed_until") > now


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError("timestamps must include a timezone offset")

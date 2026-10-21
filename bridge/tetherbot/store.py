# SPDX-License-Identifier: GPL-2.0-or-later
"""Item store, diff, and local expiry.

``replace_origin`` is the successful-read path. A failed read must not call
it with an empty list, or that origin's items would be removed. A snooze
and ``expires_at`` are applied locally. Notifications come from
``notify_policy``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from tetherbot import SCHEMA_VERSION
from tetherbot.files import write_private_json
from tetherbot.model import Item, looks_like_secret, parse_acted, parse_iso8601, resolved_status
from tetherbot.notify_policy import Notice, NotifyPolicy, visible_notices
from tetherbot.todos import PALETTE_NAMES
from tetherbot.version_gate import check_schema

_BOT = re.compile(r"[a-z0-9-]{1,64}")
_TAG = re.compile(r"^[a-z0-9_-]{1,32}$")
FEED_STATES = frozenset({"idle", "working", "needs_you", "error"})
_SUMMARY_LIMIT = 200
_NAME_LIMIT = 40


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


@dataclass(frozen=True)
class FeedView:
    """One feed file's status block. Item titles are not part of it."""

    updated_at: str | None = None
    state: str | None = None
    summary: str | None = None
    last_run: str | None = None
    next_run: str | None = None
    stale: bool = False
    tag_colors: tuple[tuple[str, str], ...] = ()
    display_name: str | None = None


class ItemStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.load_error: str | None = None
        self._items: dict[str, Item] = {}
        self._feeds: dict[str, FeedView] = {}
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

    def tag_color_map(self) -> dict[str, str]:
        """Palette overrides from every feed. The first bot id wins a clash."""

        merged: dict[str, str] = {}
        for bot in sorted(self._feeds):
            for tag, color in self._feeds[bot].tag_colors:
                merged.setdefault(tag, color)
        return merged

    def feed(self, bot: str) -> FeedView | None:
        return self._feeds.get(bot)

    def set_feed(self, bot: str, view: FeedView) -> bool:
        """Remember a feed status block. A bad bot id is ignored."""

        if _BOT.fullmatch(bot) is None:
            return False
        if self._feeds.get(bot) == view:
            return False
        self._feeds[bot] = view
        self._save()
        return True

    def mark_feed_stale(self, bot: str) -> bool:
        """Keep the last status block and mark that feed stale."""

        if _BOT.fullmatch(bot) is None:
            return False
        current = self._feeds.get(bot, FeedView())
        if current.stale:
            return False
        self._feeds[bot] = replace(current, stale=True)
        self._save()
        return True

    def open_summary(self, bot: str, now: datetime) -> str:
        """Count visible open items. Closed, dropped, acted, and resolved items are omitted."""

        _require_aware(now)
        visible = [
            item
            for item in self._items.values()
            if item.key.startswith(f"{bot}/") and _listed(item, now)
        ]
        return _count_summary(visible)

    def open_counts(self, bot: str, now: datetime) -> tuple[int, int]:
        """Visible open asks and todos for one bot. Snoozed and acted items are omitted."""

        _require_aware(now)
        asks = 0
        todos = 0
        prefix = f"{bot}/"
        for item in self._items.values():
            if not item.key.startswith(prefix) or not _listed(item, now):
                continue
            if item.kind == "ask":
                asks += 1
            elif item.kind == "todo":
                todos += 1
        return asks, todos

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
            for notice in visible_notices(notices)
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
        self._feeds = _load_feeds(raw.get("feeds"))
        self.repo_state_dirty = any(item.acted or item.resolved for item in items)

    def _save(self) -> None:
        if self.path is None or self._block_save:
            return
        payload: dict[str, object] = {
            "schema": SCHEMA_VERSION,
            "items": [item.to_cache() for item in self.items()],
            "delivered": [list(token) for token in sorted(self._policy.delivered)],
        }
        if self._feeds:
            payload["feeds"] = {
                bot: _feed_payload(view) for bot, view in sorted(self._feeds.items())
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


def parse_feed_view(payload: Mapping[str, object]) -> FeedView:
    """Read the feed file's status block. Unknown states and bad times are dropped."""

    status = payload.get("status")
    state = None
    summary = None
    last_run = None
    next_run = None
    if isinstance(status, Mapping):
        raw_state = status.get("state")
        if isinstance(raw_state, str) and raw_state in FEED_STATES:
            state = raw_state
        summary = _clean_summary(status.get("summary"))
        last_run = _optional_time(status.get("last_run"))
        next_run = _optional_time(status.get("next_run"))
    return FeedView(
        updated_at=_optional_time(payload.get("updated_at")),
        state=state,
        summary=summary,
        last_run=last_run,
        next_run=next_run,
        tag_colors=_tag_colors(payload.get("tag_colors")),
        display_name=_published_name(payload),
    )


def fallback_display_name(bot_id: str) -> str:
    """Title-case a slug when the bot has not published a name."""

    parts = [part[:1].upper() + part[1:] for part in bot_id.split("-") if part]
    return " ".join(parts) if parts else bot_id


def resolve_display_name(bot_id: str, published: str | None, override: str | None) -> str:
    """Config override, then the name in the feed, then the title-cased slug."""

    if override:
        return override
    if published:
        return published
    return fallback_display_name(bot_id)


def clean_display_name(value: object) -> str | None:
    """A short label. A secret-shaped or over-long value is dropped, not stored."""

    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or len(text) > _NAME_LIMIT or looks_like_secret(text):
        return None
    return text


def _published_name(payload: Mapping[str, object]) -> str | None:
    published = clean_display_name(payload.get("display_name"))
    if published is not None:
        return published
    bot = payload.get("bot")
    if isinstance(bot, Mapping):
        return clean_display_name(bot.get("display_name"))
    return None


def _clean_summary(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or looks_like_secret(text):
        return None
    return text[:_SUMMARY_LIMIT]


def _optional_time(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parse_iso8601(value, field_name="updated_at")
    except ValueError:
        return None
    return value


def _count_summary(items: list[Item]) -> str:
    parts: list[str] = []
    asks = sum(item.kind == "ask" for item in items)
    todos = sum(item.kind == "todo" for item in items)
    watches = sum(item.kind == "watch" for item in items)
    notes = sum(item.kind == "notification" for item in items)
    if asks == 1:
        parts.append("1 open ask")
    elif asks:
        parts.append(f"{asks} open asks")
    if todos == 1:
        parts.append("1 todo")
    elif todos:
        parts.append(f"{todos} todos")
    if watches == 1:
        parts.append("1 watch")
    elif watches:
        parts.append(f"{watches} watches")
    if notes == 1:
        parts.append("1 notification")
    elif notes:
        parts.append(f"{notes} notifications")
    return ", ".join(parts)


def _load_feeds(value: object) -> dict[str, FeedView]:
    if not isinstance(value, Mapping):
        return {}
    feeds: dict[str, FeedView] = {}
    for bot, raw in value.items():
        if not isinstance(bot, str) or _BOT.fullmatch(bot) is None or not isinstance(raw, Mapping):
            continue
        state = raw.get("state")
        feeds[bot] = FeedView(
            updated_at=_optional_time(raw.get("updated_at")),
            state=state if isinstance(state, str) and state in FEED_STATES else None,
            summary=_clean_summary(raw.get("summary")),
            last_run=_optional_time(raw.get("last_run")),
            next_run=_optional_time(raw.get("next_run")),
            stale=raw.get("stale") is True,
            tag_colors=_stored_tag_colors(raw.get("tag_colors")),
            display_name=clean_display_name(raw.get("display_name")),
        )
    return feeds


def _feed_payload(view: FeedView) -> dict[str, object]:
    payload: dict[str, object] = {}
    if view.updated_at is not None:
        payload["updated_at"] = view.updated_at
    if view.state is not None:
        payload["state"] = view.state
    if view.summary is not None:
        payload["summary"] = view.summary
    if view.last_run is not None:
        payload["last_run"] = view.last_run
    if view.next_run is not None:
        payload["next_run"] = view.next_run
    if view.stale:
        payload["stale"] = True
    if view.tag_colors:
        payload["tag_colors"] = [[tag, color] for tag, color in view.tag_colors]
    if view.display_name is not None:
        payload["display_name"] = view.display_name
    return payload


def _tag_colors(value: object) -> tuple[tuple[str, str], ...]:
    """Keep palette entries. A bad map does not fail the feed."""

    if not isinstance(value, Mapping):
        return ()
    rows = []
    for tag, color in value.items():
        if (
            isinstance(tag, str)
            and _TAG.fullmatch(tag) is not None
            and isinstance(color, str)
            and color in PALETTE_NAMES
            and not looks_like_secret(tag)
        ):
            rows.append((tag, color))
    return tuple(sorted(rows))


def _stored_tag_colors(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    rows = []
    for entry in value:
        if (
            isinstance(entry, list)
            and len(entry) == 2
            and isinstance(entry[0], str)
            and isinstance(entry[1], str)
            and entry[1] in PALETTE_NAMES
        ):
            rows.append((entry[0], entry[1]))
    return tuple(rows)

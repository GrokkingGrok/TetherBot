# SPDX-License-Identifier: GPL-2.0-or-later
"""Session API implemented on the store and the queue.

This module does not import PyGObject and does not open a socket. The bus
export lives in ``dbus_service``. Secrets never appear in a return value,
an error message, or a signal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from tetherbot import SCHEMA_VERSION, __version__
from tetherbot.config import ConfigError, save_adapter_enabled
from tetherbot.dbus_service import INTERFACE
from tetherbot.model import ENVELOPE_ACTIONS, looks_like_secret, mask_secrets, parse_iso8601
from tetherbot.queue import QueueError
from tetherbot.store import resolve_display_name
from tetherbot.timer import TimerError
from tetherbot.todos import (
    SORTS,
    VIEWS,
    ParsedQuery,
    chips,
    matches,
    parse_query,
    sort_key,
    tag_color,
)
from tetherbot.version_gate import check_schema

NOT_FOUND = f"{INTERFACE}.Error.NotFound"
INVALID_ARGS = f"{INTERFACE}.Error.InvalidArgs"
UNAVAILABLE = f"{INTERFACE}.Error.Unavailable"
FAILED = f"{INTERFACE}.Error.Failed"
TIMER_BUSY = f"{INTERFACE}.Error.TimerBusy"
NO_TIMER = f"{INTERFACE}.Error.NoTimer"

SYNC_LIMIT_SECONDS = 30
_FILTER_KEYS = frozenset(
    {
        "kinds",
        "bots",
        "status",
        "include_snoozed",
        "tags",
        "query",
        "view",
        "include_done_days",
        "sort",
    }
)
_ITEM_OUTBOUND = frozenset({"approve", "veto", "done"})
_KNOWN_ADAPTERS = ("github-poller", "official", "webhook-sender")
_WINDOW_TARGETS = frozenset({"bots"})
_BRIDGE_BOT_STATE = frozenset(
    {"degraded", "offline", "failed_closed", "unconfigured", "paused"}
)

# Out-signature from the introspection XML. None means the method returns nothing.
METHOD_OUT: dict[str, str | None] = {
    "GetItems": "(s)",
    "GetItem": "(s)",
    "PerformAction": "(s)",
    "Snooze": "(b)",
    "MarkSeen": None,
    "SendToBot": "(s)",
    "SyncNow": None,
    "OpenChat": "(b)",
    "GetAdapters": "(s)",
    "SetAdapterEnabled": None,
    "RequestSecretEntry": "(b)",
    "ForgetSecret": None,
    "GetQueue": "(s)",
    "RetryParked": None,
    "DropQueued": None,
    "OpenWindow": "(b)",
    "GetTags": "(s)",
    "Undo": "(s)",
    "StartTimer": "(s)",
    "PauseTimer": "(s)",
    "ResumeTimer": "(s)",
    "StopTimer": "(s)",
    "UndoStopTimer": "(b)",
    "GetTimer": "(s)",
    "ResolveTimerWarning": "(s)",
    "AssignStoppedTimer": "(b)",
    "AdjustTimerStart": "(s)",
    "SetTimerStart": "(s)",
    "AssignTimer": "(s)",
    "DismissTimer": "(s)",
}

PROPERTY_TYPES = {
    "Version": "s",
    "ProtocolVersions": "as",
    "State": "s",
    "StateReason": "s",
    "Mode": "s",
    "Counts": "a{su}",
    "Bots": "s",
    "LastSync": "x",
    "QueueLength": "u",
}

SIGNAL_SIGNATURES = {
    "ItemsChanged": "(asasas)",
    "NotificationRequested": "(ss)",
    "ActionResult": "(sss)",
    "StateChanged": "(ss)",
    "TimerChanged": "(s)",
}


class ServiceError(Exception):
    """A D-Bus error. ``error_name`` is the full interface error name."""

    def __init__(self, error_name: str, message: str) -> None:
        self.error_name = error_name
        super().__init__(message)


Listener = Callable[[str, tuple[Any, ...]], None]


class BridgeApi:
    """Methods and properties for one running bridge."""

    def __init__(self, daemon: Any) -> None:
        self._daemon = daemon
        self._listeners: list[Listener] = []
        self._last_sync = 0
        self._last_sync_request: datetime | None = None
        self._seen_state = (daemon.state, daemon.reason)
        self._bots_json = _dumps(self._bots())

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def call(self, method: str, args: tuple[Any, ...]) -> tuple[Any, ...] | None:
        if method not in METHOD_OUT:
            raise ServiceError(FAILED, "unknown method")
        handler = getattr(self, f"_{_camel_to_snake(method)}")
        return handler(*args)

    def properties(self) -> dict[str, Any]:
        counts = dict(self._daemon.store.counts(now=self._daemon.now()))
        counts["queued"] = self._daemon.queue.pending_count()
        mode = "" if self._daemon.config is None else self._daemon.config.mode
        return {
            "Version": __version__,
            "ProtocolVersions": [SCHEMA_VERSION],
            "State": self._daemon.state,
            "StateReason": self._daemon.reason,
            "Mode": mode,
            "Counts": counts,
            "Bots": _dumps(self._bots()),
            "LastSync": self._last_sync,
            "QueueLength": self._daemon.queue.pending_count(),
        }

    def _get_items(self, filter_json: str) -> tuple[str]:
        spec = _object(filter_json, "filter_json")
        unknown = sorted(set(spec) - _FILTER_KEYS)
        if unknown:
            raise ServiceError(INVALID_ARGS, "unknown filter key")
        include_snoozed = bool(spec.get("include_snoozed", False))
        kinds = _string_set(spec.get("kinds"), "kinds")
        bots = _string_set(spec.get("bots"), "bots")
        status = _status_filter(spec.get("status"))
        required_tags = _string_list(spec.get("tags"), "tags")
        query = _query_filter(spec.get("query"))
        view = _view_filter(spec.get("view"))
        done_days = _done_days(spec.get("include_done_days"))
        sort = _sort_filter(spec.get("sort"))
        now = self._daemon.now()
        zone = now.tzinfo
        if zone is None:
            raise ServiceError(FAILED, "clock must be timezone-aware")
        colors = self._daemon.store.tag_color_map()
        rows = []
        for item in self._daemon.store.items():
            recent = done_days is not None and _recently_done(item, now, done_days)
            if item.status != "open" and not recent:
                continue
            if (item.acted or item.resolved) and not recent:
                continue
            if not include_snoozed and _snoozed(item.snoozed_until, now):
                continue
            if kinds is not None and item.kind not in kinds:
                continue
            if bots is not None and item.key.split("/", 1)[0] not in bots:
                continue
            if status is not None and item.status not in status:
                continue
            if not matches(
                item,
                required_tags=required_tags,
                query=query,
                view=view,
                now=now,
                zone=zone,
            ):
                continue
            rows.append(item)
        rows.sort(key=lambda item: sort_key(item, sort, now, zone))
        totals = self._tracked()
        return (
            _dumps(
                [
                    _item_payload(
                        item,
                        now,
                        zone,
                        colors,
                        totals,
                        self._display_name(item.bot),
                    )
                    for item in rows
                ]
            ),
        )

    def _get_item(self, key: str) -> tuple[str]:
        item = self._daemon.store.get(key)
        if item is None:
            raise ServiceError(NOT_FOUND, "item not found")
        now = self._daemon.now()
        zone = now.tzinfo
        if zone is None:
            raise ServiceError(FAILED, "clock must be timezone-aware")
        return (
            _dumps(
                _item_payload(
                    item,
                    now,
                    zone,
                    self._daemon.store.tag_color_map(),
                    self._tracked(),
                    self._display_name(item.bot),
                )
            ),
        )

    def _get_tags(self) -> tuple[str]:
        now = self._daemon.now()
        counts: dict[str, int] = {}
        for item in self._daemon.store.items():
            if item.status != "open" or item.acted or item.resolved:
                continue
            if _snoozed(item.snoozed_until, now):
                continue
            for tag in item.tags:
                counts[tag] = counts.get(tag, 0) + 1
        colors = self._daemon.store.tag_color_map()
        rows = [
            {"tag": tag, "count": counts[tag], "color": tag_color(tag, colors)}
            for tag in sorted(counts)
        ]
        return (_dumps(rows),)

    def _open_window(self, item_key: str) -> tuple[bool]:
        if not isinstance(item_key, str) or (
            item_key and item_key not in _WINDOW_TARGETS and _bad_item_key(item_key)
        ):
            raise ServiceError(INVALID_ARGS, "item_key is invalid")
        hook = getattr(self._daemon, "launch_window", None)
        if hook is None:
            from tetherbot.window_launch import launch_window as hook
        try:
            opened = bool(hook(item_key))
        except Exception:
            opened = False
        return (opened,)

    def note_timer(self) -> None:
        timer = getattr(self._daemon, "timer", None)
        if timer is None:
            return
        self._emit("TimerChanged", _dumps(timer.view()))

    def _tracked(self) -> dict[str, int]:
        timer = getattr(self._daemon, "timer", None)
        if timer is None:
            return {}
        return timer.totals()

    def _timer_call(self, action: str, *args: Any) -> Any:
        timer = getattr(self._daemon, "timer", None)
        if timer is None:
            raise ServiceError(FAILED, "Could not save the timer")
        try:
            return getattr(timer, action)(*args)
        except TimerError as exc:
            raise _timer_error(exc) from exc

    def _start_timer(self, item_key: str) -> tuple[str]:
        if not isinstance(item_key, str):
            raise ServiceError(INVALID_ARGS, "item_key is invalid")
        timer = getattr(self._daemon, "timer", None)
        if timer is not None and timer.holding() is not None:
            raise ServiceError(TIMER_BUSY, "a timer is already running")
        title = ""
        if item_key:
            if _bad_item_key(item_key):
                raise ServiceError(INVALID_ARGS, "item_key is invalid")
            item = self._daemon.store.get(item_key)
            if item is None or item.kind != "todo" or item.status != "open":
                raise ServiceError(NOT_FOUND, "item not found")
            title = item.title
        payload = self._timer_call("start", item_key, title)
        self._emit("TimerChanged", _dumps(payload))
        return (_dumps(payload),)

    def _pause_timer(self) -> tuple[str]:
        payload = self._timer_call("pause")
        self._emit("TimerChanged", _dumps(payload))
        return (_dumps(payload),)

    def _resume_timer(self) -> tuple[str]:
        payload = self._timer_call("resume")
        self._emit("TimerChanged", _dumps(payload))
        return (_dumps(payload),)

    def _stop_timer(self) -> tuple[str]:
        result = self._timer_call("stop")
        self.note_timer()
        return (_dumps(result),)

    def _undo_stop_timer(self, timer_id: str) -> tuple[bool]:
        if not isinstance(timer_id, str) or not timer_id:
            raise ServiceError(INVALID_ARGS, "timer_id is invalid")
        ok = bool(self._timer_call("undo_stop", timer_id))
        if ok:
            self.note_timer()
        return (ok,)

    def _get_timer(self) -> tuple[str]:
        timer = getattr(self._daemon, "timer", None)
        if timer is None:
            return (_dumps({"schema": "tetherbot/1", "state": "idle"}),)
        changed = bool(timer.poll())
        payload = timer.view()
        if changed:
            self._emit("TimerChanged", _dumps(payload))
        return (_dumps(payload),)

    def _resolve_timer_warning(self, choice: str, seconds: int) -> tuple[str]:
        if not isinstance(choice, str):
            raise ServiceError(INVALID_ARGS, "choice is invalid")
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            raise ServiceError(INVALID_ARGS, "seconds is invalid")
        payload = self._timer_call("resolve", choice, seconds)
        self.note_timer()
        return (_dumps(payload),)

    def _assign_stopped_timer(self, timer_id: str, item_key: str) -> tuple[bool]:
        if not isinstance(timer_id, str) or not timer_id:
            raise ServiceError(INVALID_ARGS, "timer_id is invalid")
        if not isinstance(item_key, str) or _bad_item_key(item_key):
            raise ServiceError(INVALID_ARGS, "item_key is invalid")
        item = self._daemon.store.get(item_key)
        if item is None or item.kind != "todo" or item.status != "open":
            raise ServiceError(NOT_FOUND, "item not found")
        ok = bool(self._timer_call("assign", timer_id, item_key))
        if ok:
            self.note_timer()
        return (ok,)

    def _adjust_timer_start(self, delta_s: int) -> tuple[str]:
        if isinstance(delta_s, bool) or not isinstance(delta_s, int):
            raise ServiceError(INVALID_ARGS, "delta is invalid")
        payload = self._timer_call("adjust_start", delta_s)
        self.note_timer()
        return (_dumps(payload),)

    def _set_timer_start(self, started_at: int) -> tuple[str]:
        if isinstance(started_at, bool) or not isinstance(started_at, int):
            raise ServiceError(INVALID_ARGS, "started_at is invalid")
        payload = self._timer_call("set_start", started_at)
        self.note_timer()
        return (_dumps(payload),)

    def _assign_timer(self, item_key: str) -> tuple[str]:
        if not isinstance(item_key, str) or _bad_item_key(item_key):
            raise ServiceError(INVALID_ARGS, "item_key is invalid")
        item = self._daemon.store.get(item_key)
        if item is None or item.kind != "todo" or item.status != "open":
            raise ServiceError(NOT_FOUND, "item not found")
        payload = self._timer_call("attach", item_key, item.title)
        self.note_timer()
        return (_dumps(payload),)

    def _dismiss_timer(self) -> tuple[str]:
        payload = self._timer_call("dismiss")
        self.note_timer()
        return (_dumps(payload),)

    def _stop_owned_timer(self, key: str) -> None:
        timer = getattr(self._daemon, "timer", None)
        if timer is None:
            return
        current = timer.active()
        if current is None or current.get("item_key") != key:
            return
        self._timer_call("stop")
        self.note_timer()

    def _undo(self, item_key: str) -> tuple[str]:
        if not isinstance(item_key, str) or _bad_item_key(item_key):
            raise ServiceError(INVALID_ARGS, "item_key is invalid")
        item = self._daemon.store.get(item_key)
        if item is None:
            raise ServiceError(NOT_FOUND, "item not found")
        queued = [
            action
            for action in self._daemon.queue.snapshot()
            if action.item == item_key and action.action == "done"
        ]
        unsent = [action for action in queued if action.state == "pending" and action.attempts == 0]
        if unsent:
            ids = [action.action_id for action in unsent]
            for action_id in ids:
                self._daemon.queue.drop(action_id)
            self._release_closed(ids)
            self._emit_properties("QueueLength", "Counts")
            self.note_bots()
            return (_dumps({"result": "dropped"}),)
        sent = [
            action
            for action in queued
            if action.attempts > 0 or action.state == "parked"
        ]
        for action in sent:
            self._daemon.queue.drop(action.action_id)
        if sent:
            self._release_closed([action.action_id for action in sent])
        elif item.acted is not None:
            self._release_closed([item.acted["action_id"]])
        elif item.status == "open" and item.resolved is None:
            raise ServiceError(INVALID_ARGS, "nothing to undo")
        bot = item_key.split("/", 1)[0]
        action_id = self._enqueue(bot, item_key, "reopen", {})
        return (_dumps({"result": "reopen", "action_id": action_id}),)

    def _perform_action(self, key: str, action: str, args_json: str) -> tuple[str]:
        item = self._daemon.store.get(key)
        if item is None:
            raise ServiceError(NOT_FOUND, "item not found")
        if action == "snooze":
            raise ServiceError(INVALID_ARGS, "snooze is local")
        if action == "open_chat":
            raise ServiceError(INVALID_ARGS, "open_chat is not an outbound action")
        if action not in item.actions or action not in _ITEM_OUTBOUND:
            raise ServiceError(INVALID_ARGS, "action is not listed on the item")
        if item.status != "open":
            raise ServiceError(INVALID_ARGS, "item is not open")
        args = _object(args_json, "args_json")
        if args:
            raise ServiceError(INVALID_ARGS, "this action does not take arguments")
        if action == "done":
            self._stop_owned_timer(key)
        bot = key.split("/", 1)[0]
        return (self._enqueue(bot, key, action, args),)

    def _snooze(self, key: str, until_iso: str) -> tuple[bool]:
        try:
            until = parse_iso8601(until_iso, field_name="until")
        except ValueError as exc:
            raise ServiceError(INVALID_ARGS, "until must be an ISO 8601 timestamp") from exc
        ok = self._daemon.store.snooze(key, until, now=self._daemon.now())
        if ok:
            self._emit("ItemsChanged", [], [key], [])
            self._emit_properties("Counts")
            self.note_bots()
        return (ok,)

    def _mark_seen(self, keys: list[str]) -> None:
        if isinstance(keys, str) or not isinstance(keys, (list, tuple)):
            raise ServiceError(INVALID_ARGS, "keys must be an array of strings")
        if not all(isinstance(key, str) for key in keys):
            raise ServiceError(INVALID_ARGS, "keys must be an array of strings")
        changed = []
        for key in keys:
            item = self._daemon.store.get(key)
            if item is not None and not item.seen:
                changed.append(key)
        if changed:
            self._daemon.store.mark_seen(changed)
            self._emit("ItemsChanged", [], changed, [])
        return None

    def _send_to_bot(self, bot: str, payload_json: str) -> tuple[str]:
        if not isinstance(bot, str) or not bot:
            raise ServiceError(INVALID_ARGS, "bot is required")
        payload = _object(payload_json, "payload_json")
        action = _one_action(payload)
        name = action.get("action")
        item = action.get("item")
        args = action.get("args", {})
        if not isinstance(name, str) or name not in ENVELOPE_ACTIONS:
            raise ServiceError(INVALID_ARGS, "action is not in the protocol set")
        if not isinstance(item, str) or not item.startswith(f"{bot}/"):
            raise ServiceError(INVALID_ARGS, "item key must start with the bot id")
        if not isinstance(args, dict):
            raise ServiceError(INVALID_ARGS, "args must be an object")
        action_id = action.get("action_id")
        if action_id is not None and not isinstance(action_id, str):
            raise ServiceError(INVALID_ARGS, "action_id must be a string")
        return (self._enqueue(bot, item, name, args, action_id=action_id),)

    def _sync_now(self) -> None:
        now = self._daemon.now()
        previous = self._last_sync_request
        if previous is not None and (now - previous).total_seconds() < SYNC_LIMIT_SECONDS:
            return None
        self._last_sync_request = now
        return None

    def _open_chat(self, bot: str) -> tuple[bool]:
        del bot
        return (False,)

    def _get_adapters(self) -> tuple[str]:
        enabled = {}
        if self._daemon.config is not None:
            enabled = {name: row.enabled for name, row in self._daemon.config.adapters.items()}
        rows = []
        for name in _KNOWN_ADAPTERS:
            is_on = bool(enabled.get(name, False))
            state = "not-started" if is_on else "disabled"
            last_error = ""
            version_gate = SCHEMA_VERSION
            next_poll = 0
            live = self._adapter_live(name)
            if live is not None:
                state, last_error, version_gate, next_poll = live
            rows.append(
                {
                    "name": name,
                    "enabled": is_on,
                    "state": state,
                    "version_gate": version_gate,
                    "last_error": last_error,
                    "next_poll": next_poll,
                }
            )
        return (_dumps(rows),)

    def _adapter_live(self, name: str) -> tuple[str, str, str, int] | None:
        if name == "webhook-sender":
            sender = getattr(self._daemon, "webhook", None)
            if sender is None:
                return None
            status = sender.status()
            profile = str(getattr(sender, "profile", SCHEMA_VERSION))
            return status.state, status.detail, profile, int(sender.next_poll())
        if name == "github-poller":
            poller = getattr(self._daemon, "poller", None)
            if poller is None:
                return None
            status = poller.status()
            return status.state, status.detail, SCHEMA_VERSION, int(poller.next_poll())
        return None

    def _set_adapter_enabled(self, name: str, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ServiceError(INVALID_ARGS, "enabled must be a boolean")
        try:
            save_adapter_enabled(self._daemon.config_path, name, enabled)
        except ConfigError as exc:
            message = str(exc)
            code = INVALID_ARGS if message.startswith("unknown adapter") else FAILED
            raise ServiceError(code, message) from exc
        self._daemon.reload_config()
        self._note_state()
        return None

    def publish_state(self) -> None:
        self._note_state()

    def emit_items_changed(self, added: list[str], updated: list[str], removed: list[str]) -> None:
        self._emit("ItemsChanged", list(added), list(updated), list(removed))
        self._emit_properties("Counts")
        self.note_bots()

    def emit_action_result(self, action_id: str, result: str, detail: str) -> None:
        self._emit("ActionResult", action_id, result, mask_secrets(detail))

    def emit_queue_changed(self) -> None:
        """Tell property watchers that QueueLength and Counts.queued changed.

        Both counts are pending actions only. Parked actions stay in GetQueue
        and are not included, so a park and an accept both emit this.
        """

        self._emit_properties("QueueLength", "Counts")

    def emit_notification(self, item_json: str, reason: str) -> None:
        self._emit("NotificationRequested", mask_secrets(item_json), reason)

    def _request_secret_entry(self, slot: str) -> tuple[bool]:
        """The key dialog is a later milestone. False means it did not open."""

        _reject_slot(slot)
        return (False,)

    def _forget_secret(self, slot: str) -> None:
        from tetherbot.secrets import SecretError, SecretLocked, SecretUnavailable, SecretValueError

        _reject_slot(slot)
        try:
            self._daemon.secrets.forget(slot)
        except SecretValueError as exc:
            raise ServiceError(INVALID_ARGS, str(exc)) from exc
        except SecretLocked as exc:
            raise ServiceError(FAILED, str(exc)) from exc
        except SecretUnavailable as exc:
            raise ServiceError(UNAVAILABLE, str(exc)) from exc
        except SecretError as exc:
            raise ServiceError(FAILED, str(exc)) from exc

    def _get_queue(self) -> tuple[str]:
        rows = []
        for action in self._daemon.queue.snapshot():
            rows.append(
                {
                    "action_id": action.action_id,
                    "bot": action.bot,
                    "item": action.item,
                    "action": action.action,
                    "args": action.args,
                    "created": action.created,
                    "state": action.state,
                    "attempts": action.attempts,
                    "detail": mask_secrets(action.detail),
                }
            )
        return (_dumps(rows),)

    def _retry_parked(self, action_id: str) -> None:
        row = self._find_queued(action_id)
        if row.state != "parked":
            raise ServiceError(INVALID_ARGS, "action is not parked")
        self._daemon.queue.retry(action_id)
        sender = getattr(self._daemon, "webhook", None)
        if sender is not None:
            sender.resume(row.bot)
        self._hide_again(row)
        self._emit_properties("QueueLength", "Counts")
        self.note_bots()
        return None

    def _drop_queued(self, action_id: str) -> None:
        row = self._find_queued(action_id)
        self._daemon.queue.drop(action_id)
        self._release_closed([row.action_id])
        self._emit_properties("QueueLength", "Counts")
        self.note_bots()
        return None

    def _enqueue(
        self,
        bot: str,
        item: str,
        action: str,
        args: dict[str, Any],
        action_id: str | None = None,
    ) -> str:
        try:
            chosen = self._daemon.queue.enqueue(
                bot=bot,
                item=item,
                action=action,
                args=args,
                created=self._daemon.now().isoformat(),
                action_id=action_id,
            )
        except QueueError as exc:
            raise ServiceError(INVALID_ARGS, str(exc)) from exc
        if action in _ITEM_OUTBOUND:
            self._daemon.store.record_action(item, action, chosen, self._daemon.now())
            self._emit("ItemsChanged", [], [item], [])
            self._request_state_write()
        self._emit_properties("QueueLength", "Counts")
        self.note_bots()
        return chosen

    def _hide_again(self, row: Any) -> None:
        if row.action not in _ITEM_OUTBOUND:
            return
        try:
            at = parse_iso8601(row.created, field_name="created")
        except ValueError:
            at = self._daemon.now()
        if self._daemon.store.record_action(row.item, row.action, row.action_id, at):
            self._emit("ItemsChanged", [], [row.item], [])
            self._request_state_write()
            self.note_bots()

    def _release_closed(self, action_ids: list[str]) -> None:
        changed = self._daemon.store.release_actions(action_ids)
        if not changed:
            return
        self._emit("ItemsChanged", [], changed, [])
        self._request_state_write()
        self.note_bots()

    def _request_state_write(self) -> None:
        poller = getattr(self._daemon, "poller", None)
        if poller is not None and hasattr(poller, "request_state_write"):
            poller.request_state_write()

    def _find_queued(self, action_id: str) -> Any:
        for action in self._daemon.queue.snapshot():
            if action.action_id == action_id:
                return action
        raise ServiceError(NOT_FOUND, "action is not in the queue")

    def _bots(self) -> list[dict[str, Any]]:
        names: set[str] = set()
        config = self._daemon.config
        if config is not None:
            names.update(config.bots)
        store = self._daemon.store
        for item in store.items():
            names.add(item.key.split("/", 1)[0])
        now = self._daemon.now()
        rows = []
        for name in sorted(names):
            view = store.feed(name)
            summary = "" if view is None or not view.summary else view.summary
            if not summary:
                summary = store.open_summary(name, now)
            slot = ""
            override = ""
            if config is not None and name in config.bots:
                slot = config.bots[name].webhook_slot
                override = config.bots[name].display_name
            asks, todos = store.open_counts(name, now)
            published = None if view is None else view.display_name
            rows.append(
                {
                    "name": name,
                    "display_name": resolve_display_name(name, published, override or None),
                    "state": self._bot_state(view),
                    "summary": summary,
                    "last_seen": _feed_last_seen(view),
                    "next_run": _epoch(None if view is None else view.next_run),
                    "open_asks": asks,
                    "open_todos": todos,
                    "routes": {"outbound": bool(slot)},
                }
            )
        return rows

    def _display_name(self, bot: str) -> str:
        view = self._daemon.store.feed(bot)
        published = None if view is None else view.display_name
        override = ""
        config = self._daemon.config
        if config is not None and bot in config.bots:
            override = config.bots[bot].display_name
        return resolve_display_name(bot, published, override or None)

    def _bot_state(self, view: Any) -> str:
        bridge = self._daemon.state or "ok"
        if bridge in _BRIDGE_BOT_STATE:
            return bridge
        if view is not None and view.stale:
            return "degraded"
        if view is not None and view.state:
            return view.state
        return bridge

    def note_bots(self) -> None:
        """Emit ``Bots`` when the serialized row list changed."""

        text = _dumps(self._bots())
        if text == self._bots_json:
            return
        self._bots_json = text
        self._emit_properties("Bots")

    def _note_state(self) -> None:
        current = (self._daemon.state, self._daemon.reason)
        if current == self._seen_state:
            return
        self._seen_state = current
        self._emit("StateChanged", current[0], current[1])
        self._emit_properties("State", "StateReason", "Mode")
        self.note_bots()

    def _emit_properties(self, *names: str) -> None:
        self._emit("PropertiesChanged", names)

    def _emit(self, name: str, *args: Any) -> None:
        payload = tuple(args)
        for listener in tuple(self._listeners):
            listener(name, payload)


def _camel_to_snake(name: str) -> str:
    chars: list[str] = []
    for char in name:
        if char.isupper() and chars:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _epoch(value: str | None) -> int:
    parsed = _epoch_or_none(value)
    return 0 if parsed is None else parsed


def _epoch_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(parse_iso8601(value, field_name="updated_at").timestamp())
    except ValueError:
        return None


def _feed_last_seen(view: Any) -> int:
    """Feed ``updated_at``, or ``status.last_run`` when that time is later."""

    if view is None:
        return 0
    updated = _epoch_or_none(view.updated_at)
    last_run = _epoch_or_none(view.last_run)
    if updated is None:
        return 0 if last_run is None else last_run
    if last_run is None or last_run <= updated:
        return updated
    return last_run


def _object(text: str, field_name: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ServiceError(INVALID_ARGS, f"{field_name} must be a JSON object")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ServiceError(INVALID_ARGS, f"{field_name} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ServiceError(INVALID_ARGS, f"{field_name} must be a JSON object")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ServiceError(INVALID_ARGS, f"{field_name} must be an array of strings")
    return list(value)


def _query_filter(value: object) -> ParsedQuery:
    if value is None:
        return ParsedQuery()
    if not isinstance(value, str):
        raise ServiceError(INVALID_ARGS, "query must be a string")
    return parse_query(value)


def _view_filter(value: object) -> str:
    if value is None or value == "":
        return "all"
    if not isinstance(value, str) or value not in VIEWS:
        raise ServiceError(INVALID_ARGS, "view must be all, mine, bots, waiting, or today")
    return value


def _sort_filter(value: object) -> str:
    if value is None or value == "":
        return "due"
    if not isinstance(value, str) or value not in SORTS:
        raise ServiceError(INVALID_ARGS, "sort must be due, priority, created, or updated")
    return value


def _done_days(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 30:
        raise ServiceError(INVALID_ARGS, "include_done_days must be an integer from 0 to 30")
    return value


def _recently_done(item: Any, now: datetime, days: int) -> bool:
    if item.status != "done" and item.resolved != "done":
        return False
    stamp = item.updated_at
    if item.acted is not None and item.acted.get("at"):
        stamp = item.acted["at"]
    try:
        closed = parse_iso8601(stamp, field_name="updated_at")
    except ValueError:
        return False
    return (now - closed).total_seconds() <= days * 86400


def _bad_item_key(key: str) -> bool:
    if key.count("/") != 1:
        return True
    bot, item_id = key.split("/", 1)
    if not bot or not item_id or "/" in item_id:
        return True
    return looks_like_secret(key)


def _string_set(value: object, field_name: str) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ServiceError(INVALID_ARGS, f"{field_name} must be an array of strings")
    return set(value)


def _status_filter(value: object) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return _string_set(value, "status")


def _snoozed(until: str | None, now: datetime) -> bool:
    if not until:
        return False
    return parse_iso8601(until, field_name="snoozed_until") > now


def _timer_error(exc: TimerError) -> ServiceError:
    names = {
        "busy": TIMER_BUSY,
        "no_timer": NO_TIMER,
        "not_found": NOT_FOUND,
        "invalid": INVALID_ARGS,
        "failed": FAILED,
    }
    return ServiceError(names.get(exc.code, FAILED), str(exc))


def _item_payload(
    item: Any,
    now: datetime,
    zone: Any,
    colors: Mapping[str, str],
    totals: Mapping[str, int] | None = None,
    display_name: str = "",
) -> dict[str, Any]:
    payload = item.protocol_dict()
    payload["key"] = item.key
    payload["origin"] = item.origin
    if display_name:
        payload["display_name"] = display_name
    payload["chips"] = chips(item, now, zone, colors)
    tracked = 0 if totals is None else int(totals.get(item.key, 0))
    if tracked > 0:
        payload["time_tracked_s"] = tracked
    local: dict[str, Any] = {
        "done_locally": item.done_locally,
        "seen": item.seen,
        "snoozed_until": item.snoozed_until,
    }
    if item.acted:
        local["acted"] = dict(item.acted)
    if item.resolved:
        local["resolved"] = item.resolved
    payload["local"] = local
    payload["redacted_fields"] = list(item.redacted_fields)
    return payload


def _one_action(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if "schema" not in payload and "type" not in payload:
        return payload
    schema = payload.get("schema")
    decision = check_schema(schema, source="payload")
    if not decision.accepted:
        if isinstance(schema, str) and looks_like_secret(schema):
            raise ServiceError(FAILED, "payload: unsupported schema, update tetherbot")
        raise ServiceError(FAILED, decision.message)
    if payload.get("type") != "actions":
        raise ServiceError(INVALID_ARGS, "payload type must be actions")
    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
        raise ServiceError(INVALID_ARGS, "SendToBot accepts one action")
    return actions[0]


def _reject_slot(slot: str) -> None:
    if not isinstance(slot, str) or looks_like_secret(slot):
        raise ServiceError(INVALID_ARGS, "slot is not a name")

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
from tetherbot.version_gate import check_schema

NOT_FOUND = f"{INTERFACE}.Error.NotFound"
INVALID_ARGS = f"{INTERFACE}.Error.InvalidArgs"
UNAVAILABLE = f"{INTERFACE}.Error.Unavailable"
FAILED = f"{INTERFACE}.Error.Failed"

SYNC_LIMIT_SECONDS = 30
_FILTER_KEYS = frozenset({"kinds", "bots", "status", "include_snoozed"})
_ITEM_OUTBOUND = frozenset({"approve", "veto", "done"})
_KNOWN_ADAPTERS = ("github-poller", "official", "webhook-sender")

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
        now = self._daemon.now()
        rows = []
        for item in self._daemon.store.items():
            if item.acted or item.resolved:
                continue
            if not include_snoozed and _snoozed(item.snoozed_until, now):
                continue
            if kinds is not None and item.kind not in kinds:
                continue
            if bots is not None and item.key.split("/", 1)[0] not in bots:
                continue
            if status is not None and item.status not in status:
                continue
            rows.append(_item_payload(item))
        return (_dumps(rows),)

    def _get_item(self, key: str) -> tuple[str]:
        item = self._daemon.store.get(key)
        if item is None:
            raise ServiceError(NOT_FOUND, "item not found")
        return (_dumps(_item_payload(item)),)

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
        return None

    def _drop_queued(self, action_id: str) -> None:
        row = self._find_queued(action_id)
        self._daemon.queue.drop(action_id)
        self._release_closed([row.action_id])
        self._emit_properties("QueueLength", "Counts")
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

    def _release_closed(self, action_ids: list[str]) -> None:
        changed = self._daemon.store.release_actions(action_ids)
        if not changed:
            return
        self._emit("ItemsChanged", [], changed, [])
        self._request_state_write()

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
        items = self._daemon.store.items()
        for item in items:
            names.add(item.key.split("/", 1)[0])
        rows = []
        for name in sorted(names):
            owned = [item for item in items if item.key.startswith(f"{name}/")]
            summary = ""
            last_seen = 0
            if owned:
                latest = max(owned, key=lambda item: item.updated_at)
                summary = latest.title
                seen_at = parse_iso8601(latest.updated_at, field_name="updated_at")
                last_seen = int(seen_at.timestamp())
            slot = ""
            if config is not None and name in config.bots:
                slot = config.bots[name].webhook_slot
            rows.append(
                {
                    "name": name,
                    "display_name": name,
                    "state": self._daemon.state,
                    "summary": summary,
                    "last_seen": last_seen,
                    "routes": {"outbound": bool(slot)},
                }
            )
        return rows

    def _note_state(self) -> None:
        current = (self._daemon.state, self._daemon.reason)
        if current == self._seen_state:
            return
        self._seen_state = current
        self._emit("StateChanged", current[0], current[1])
        self._emit_properties("State", "StateReason", "Mode", "Bots")

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


def _item_payload(item: Any) -> dict[str, Any]:
    payload = item.protocol_dict()
    payload["key"] = item.key
    payload["origin"] = item.origin
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

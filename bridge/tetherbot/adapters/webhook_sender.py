# SPDX-License-Identifier: GPL-2.0-or-later
"""Outbound webhook sender.

Posts one coalesced batch per bot with ``Authorization: Bearer``. The URL
and key stay in the secret service and are never logged. Redirects are not
followed. Retry timing matches SPEC section 7.2. The invalid-payload wording
for HTTP 400 is still **TBD, verify**, so every 400 uses the rate-cap table.

A 401 or 403 stops that bot's route, parks its actions, and asks for the key
again. Until the key dialog exists, ``tetherbotctl secret set`` retries those
parked actions when the bridge is on the bus. A poll burst is recorded after
HTTP 200. This module does not start github-poller; a running poller
consumes those times.
"""

from __future__ import annotations

import json
import logging
import random
import secrets
import ssl
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from tetherbot import SCHEMA_VERSION, __version__
from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult
from tetherbot.model import mask_secrets, parse_iso8601
from tetherbot.secrets import SecretError, SecretLocked, SecretUnavailable

PROFILE = "routine-webhook-2026-10"
_POST_TIMEOUT = 30
_MAX_TRIES = 8
_BACKOFF_SECONDS = (60, 120, 240, 480, 960, 1800)
_BURST_SECONDS = (30, 60, 120, 240)
_RETRY_PREFIX = "retry-after:"
_TIMEOUT_PREFIX = "timeout-retry-after:"
_STATUS = "status"
_LOG = logging.getLogger("tetherbot")

Post = Callable[[str, str, bytes], "HttpOutcome"]
Online = Callable[[], bool]
Jitter = Callable[[int], float]


@dataclass(frozen=True)
class HttpOutcome:
    """A secret-free description of one POST. ``body`` is never kept."""

    kind: str
    status: int | None = None


@dataclass(frozen=True)
class Plan:
    count_post: bool
    result: str
    detail: str
    stop: str | None
    hold_prefix: str | None
    notify: str | None
    title: str | None


class WebhookSender:
    name = "webhook-sender"
    direction = frozenset({"outbound"})
    profile = PROFILE

    def __init__(
        self,
        *,
        post: Post | None = None,
        online: Online | None = None,
        jitter: Jitter | None = None,
    ) -> None:
        self._post = post
        self._online = online if online is not None else network_online
        self._jitter = jitter if jitter is not None else _default_jitter
        self._ctx: Any = None
        self._running = False
        self._inflight = False
        self._generation = 0
        self._stopped: dict[str, str] = {}
        self._notified: set[tuple[str, str]] = set()
        self.overlay: tuple[str, str] | None = None
        self.poll_burst: tuple[datetime, ...] = ()

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx
        self._running = True
        self._generation += 1
        self._load_stops()
        if self._stopped:
            self.overlay = ("degraded", next(iter(self._stopped.values())))

    def stop(self) -> None:
        self._running = False
        self._generation += 1
        self._ctx = None

    def poll(self) -> PollResult:
        return PollResult(items=[], errors=["webhook-sender is outbound only"])

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        del bot, batch
        return SendResult(status="unavailable", detail="webhook-sender drains the action queue")

    def status(self) -> AdapterStatus:
        if not self._running:
            return AdapterStatus(self.name, False, "disabled", "")
        if self._stopped:
            detail = next(iter(self._stopped.values()))
            return AdapterStatus(self.name, True, "rejected-key", detail)
        if self.overlay is not None:
            state = "offline" if self.overlay[0] == "offline" else "degraded"
            return AdapterStatus(self.name, True, state, self.overlay[1])
        return AdapterStatus(self.name, True, "running", "")

    def next_poll(self) -> int:
        ctx = self._ctx
        if ctx is None:
            return 0
        soonest: datetime | None = None
        for action in ctx.queue.snapshot():
            if action.state != "pending":
                continue
            moment = _retry_at(action.detail)
            if moment is not None and (soonest is None or moment < soonest):
                soonest = moment
        if soonest is None:
            return 0
        return int(soonest.timestamp())

    def resume(self, bot: str) -> None:
        """Let a stopped route send again. ``RetryParked`` is what calls this."""

        self._clear_stop(bot)

    def tick(self) -> None:
        """Send at most one due batch. Injected posts run on the caller thread."""

        ctx = self._ctx
        if not self._running or ctx is None or self._inflight:
            return
        if not self._online():
            self._set_overlay("offline", "offline")
            return
        if self.overlay == ("offline", "offline"):
            self._set_overlay_value(None)
        batch = self._select(ctx)
        if batch is None:
            return
        bot = batch[0].bot
        secret = self._lookup(ctx, bot)
        if secret is None:
            return
        body = _envelope(batch, ctx.now(), _item_index(ctx))
        timeout_retry = any(action.detail.startswith(_TIMEOUT_PREFIX) for action in batch)
        self._inflight = True
        generation = self._generation
        if self._post is not None:
            outcome = self._call(secret.url, secret.key, body)
            self._deliver(ctx, batch, outcome, timeout_retry, generation)
            return
        threading.Thread(
            target=self._background,
            args=(ctx, batch, secret.url, secret.key, body, timeout_retry, generation),
            daemon=True,
        ).start()

    def _select(self, ctx: Any) -> tuple[Any, ...] | None:
        now = ctx.now()
        pending: dict[str, list[Any]] = {}
        for action in ctx.queue.snapshot():
            if action.state == "pending":
                pending.setdefault(action.bot, []).append(action)
        held = set(self._stopped)
        for bot, rows in pending.items():
            if bot in held:
                continue
            moment = _hold(rows)
            if moment is not None and now < moment:
                held.add(bot)
        return ctx.queue.next_batch(now, skip=frozenset(held))

    def _lookup(self, ctx: Any, bot: str) -> Any:
        config = ctx.config
        bot_config = None if config is None else config.bots.get(bot)
        if bot_config is None:
            self._set_overlay("degraded", "bot has no webhook slot")
            self._notify_once(bot, "missing-slot", "Webhook paused", "bot has no webhook slot", "")
            return None
        try:
            status = ctx.secrets.status()
        except Exception:
            status = "missing"
        if status != "available":
            self._hold_for_keyring()
            return None
        try:
            secret = ctx.secrets.get_webhook(bot_config.webhook_slot)
        except SecretLocked:
            self._hold_for_keyring()
            return None
        except SecretUnavailable:
            self._hold_for_keyring()
            return None
        except SecretError:
            self._set_overlay("degraded", "webhook secret is unreadable")
            return None
        if secret is None:
            self._set_overlay("degraded", "webhook secret is not stored")
            self._notify_once(
                bot,
                "missing-secret",
                "Re-paste key",
                "Bot details, Routines, the routine, Webhook, key",
                bot_config.webhook_slot,
            )
            return None
        return secret

    def _background(
        self,
        ctx: Any,
        batch: tuple[Any, ...],
        url: str,
        key: str,
        body: bytes,
        timeout_retry: bool,
        generation: int,
    ) -> None:
        outcome = self._call(url, key, body)

        def _finish() -> None:
            self._deliver(ctx, batch, outcome, timeout_retry, generation)

        idle = getattr(getattr(ctx, "loop", None), "idle_add", None)
        if idle is not None:
            idle(_finish)
        else:
            _finish()

    def _call(self, url: str, key: str, body: bytes) -> HttpOutcome:
        try:
            if self._post is not None:
                return self._post(url, key, body)
            return post_json(url, key, body)
        except Exception:
            _LOG.info("webhook post failed")
            return HttpOutcome("network")

    def _deliver(
        self,
        ctx: Any,
        batch: tuple[Any, ...],
        outcome: HttpOutcome,
        timeout_retry: bool,
        generation: int,
    ) -> None:
        self._inflight = False
        if not self._running or generation != self._generation or self._ctx is None:
            return
        bot = batch[0].bot
        attempts = max(action.attempts for action in batch) + 1
        plan = plan_for(outcome, timeout_retry=timeout_retry, attempts=attempts)
        ids = [action.action_id for action in batch]
        if plan.count_post:
            ctx.queue.mark_attempt(bot, ids, now=ctx.now())
            if outcome.status is None:
                _LOG.info("webhook post bot=%s result=%s", bot, plan.result)
            else:
                _LOG.info(
                    "webhook post bot=%s result=%s status=%s",
                    bot,
                    plan.result,
                    outcome.status,
                )
        if plan.result == "accepted":
            self._accept(ctx, bot, batch)
            return
        if plan.hold_prefix is not None:
            self._defer(ctx, bot, ids, plan, attempts)
            return
        if plan.stop is not None:
            self._stop_bot(ctx, bot, plan)
            return
        self._park_ids(ctx, bot, ids, plan)

    def _accept(self, ctx: Any, bot: str, batch: tuple[Any, ...]) -> None:
        ids = [action.action_id for action in batch]
        ctx.queue.accept(ids)
        ctx.api.emit_queue_changed()
        for action_id in ids:
            ctx.api.emit_action_result(action_id, "accepted", "")
        _resolve_closed(ctx, batch)
        now = ctx.now()
        self.poll_burst = tuple(now + timedelta(seconds=offset) for offset in _BURST_SECONDS)
        self._notified = {item for item in self._notified if item[0] != bot}
        if self.overlay is not None and self.overlay[0] != "offline" and not self._stopped:
            self._set_overlay_value(None)
        else:
            ctx.publish_overlay()

    def _defer(self, ctx: Any, bot: str, ids: list[str], plan: Plan, attempts: int) -> None:
        delay = _backoff(attempts)
        when = ctx.now() + timedelta(seconds=delay + self._jitter(delay))
        detail = f"{plan.hold_prefix}{when.isoformat()}"
        for action_id in ids:
            ctx.queue.note(action_id, detail)
            ctx.api.emit_action_result(action_id, "queued_retry", detail)
        del bot

    def _stop_bot(self, ctx: Any, bot: str, plan: Plan) -> None:
        ids = [action.action_id for action in ctx.queue.snapshot() if action.bot == bot]
        for action_id in ids:
            ctx.queue.park(action_id, plan.detail)
            ctx.api.emit_action_result(action_id, plan.result, plan.detail)
        ctx.api.emit_queue_changed()
        _release_closed(ctx, ids)
        self._stopped[bot] = plan.detail
        self._write_stops()
        self._set_overlay("degraded", plan.detail)
        slot = ""
        config = ctx.config
        if config is not None and bot in config.bots:
            slot = config.bots[bot].webhook_slot
        if plan.notify and plan.title:
            self._notify_once(bot, plan.detail, plan.title, _notify_body(plan), slot)

    def _park_ids(self, ctx: Any, bot: str, ids: list[str], plan: Plan) -> None:
        for action_id in ids:
            ctx.queue.park(action_id, plan.detail)
            ctx.api.emit_action_result(action_id, plan.result, plan.detail)
        ctx.api.emit_queue_changed()
        _release_closed(ctx, ids)
        if plan.notify and plan.title:
            self._notify_once(bot, plan.detail, plan.title, plan.detail, "")

    def _hold_for_keyring(self) -> None:
        """Stay pending. A locked login collection must not count as an attempt."""

        self._set_overlay("degraded", "keyring locked")
        _LOG.info("webhook waiting: keyring locked")

    def _clear_stop(self, bot: str) -> None:
        if bot not in self._stopped:
            return
        self._stopped.pop(bot, None)
        self._notified = {item for item in self._notified if item[0] != bot}
        self._write_stops()
        if not self._stopped and self.overlay is not None and self.overlay[0] == "degraded":
            self._set_overlay_value(None)

    def _set_overlay(self, state: str, reason: str) -> None:
        self._set_overlay_value((state, reason))

    def _set_overlay_value(self, overlay: tuple[str, str] | None) -> None:
        self.overlay = overlay
        ctx = self._ctx
        if ctx is not None:
            ctx.publish_overlay()

    def _notify_once(self, bot: str, kind: str, title: str, body: str, slot: str) -> None:
        key = (bot, kind)
        if key in self._notified:
            return
        self._notified.add(key)
        ctx = self._ctx
        if ctx is None:
            return
        payload: dict[str, Any] = {"body": body, "bot": bot, "title": title}
        if slot:
            payload["slot"] = slot
            payload["actions"] = ["request_secret"]
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        reason = "re-paste" if title == "Re-paste key" else "delivery_failed"
        ctx.api.emit_notification(mask_secrets(text), reason)

    def _load_stops(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        path = ctx.state_dir / "webhook-routes.json"
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        stopped = raw.get("stopped") if isinstance(raw, dict) else None
        if not isinstance(stopped, dict):
            return
        self._stopped = {
            str(bot): str(reason)
            for bot, reason in stopped.items()
            if isinstance(reason, str) and reason
        }

    def _write_stops(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        from tetherbot.files import write_private_json

        write_private_json(
            ctx.state_dir / "webhook-routes.json",
            {"schema": SCHEMA_VERSION, "stopped": dict(sorted(self._stopped.items()))},
        )


def post_json(
    url: str,
    key: str,
    body: bytes,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    timeout: int = _POST_TIMEOUT,
) -> HttpOutcome:
    """POST JSON. A redirect is not followed, so the bearer is not sent twice."""

    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        return HttpOutcome("refused")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    client = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with client.open(request, timeout=timeout) as response:
            _discard(response)
            return HttpOutcome(_STATUS, int(response.status))
    except urllib.error.HTTPError as exc:
        _discard(exc)
        return HttpOutcome(_STATUS, int(exc.code))
    except TimeoutError:
        return HttpOutcome("timeout")
    except ssl.SSLError:
        return HttpOutcome("tls")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return HttpOutcome("timeout")
        if isinstance(reason, ssl.SSLError):
            return HttpOutcome("tls")
        return HttpOutcome("network")
    except Exception:
        return HttpOutcome("network")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def plan_for(outcome: HttpOutcome, *, timeout_retry: bool, attempts: int) -> Plan:
    """Map one response onto the SPEC 7.2 table. The message has no URL or key."""

    if outcome.kind == "refused":
        return Plan(
            False,
            "rejected_key",
            "webhook url must be https",
            "re-paste key",
            None,
            "re-paste",
            "Re-paste key",
        )
    if outcome.kind == "timeout":
        if timeout_retry:
            return Plan(True, "parked", "timeout", None, None, "delivery_failed", "Webhook paused")
        return Plan(True, "queued_retry", "", None, _TIMEOUT_PREFIX, None, None)
    if outcome.kind in {"network", "tls"} or _counted_retry(outcome):
        if attempts >= _MAX_TRIES:
            return Plan(True, "parked", "rate cap", None, None, "delivery_failed", "Webhook paused")
        return Plan(True, "queued_retry", "", None, _RETRY_PREFIX, None, None)
    status = outcome.status
    if status is not None and (200 <= status < 300 or status == 409):
        # 409 is a duplicate of an action the receiver already applied.
        return Plan(True, "accepted", "", None, None, None, None)
    if status in {401, 403}:
        return Plan(
            True,
            "rejected_key",
            "re-paste key",
            "re-paste key",
            None,
            "re-paste",
            "Re-paste key",
        )
    if status in {404, 410}:
        return Plan(
            True,
            "rejected_key",
            "Routine not found",
            "Routine not found",
            None,
            "delivery_failed",
            "Routine not found",
        )
    if attempts >= _MAX_TRIES:
        return Plan(True, "parked", "rate cap", None, None, "delivery_failed", "Webhook paused")
    return Plan(True, "queued_retry", "", None, _RETRY_PREFIX, None, None)


def network_online() -> bool:
    """True when Gio is missing or the session network monitor says available."""

    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return True
    return bool(Gio.NetworkMonitor.get_default().get_network_available())


def _counted_retry(outcome: HttpOutcome) -> bool:
    status = outcome.status
    if outcome.kind != "status" or status is None or status == 200:
        return False
    if status in {401, 403, 404, 410}:
        return False
    return status == 400 or status in {301, 302, 303, 307, 308, 408, 429} or status >= 500


def client_info() -> dict[str, str]:
    """Client label on outbound JSON. ``host`` is not the machine name."""

    return {"name": "tetherbot", "version": __version__, "host": "desktop"}


def ping_body(now: datetime | None = None) -> bytes:
    """Ping POST body. ``sent_at`` and ``client`` are optional for old receivers."""

    moment = datetime.now(UTC) if now is None else now
    payload = {
        "schema": SCHEMA_VERSION,
        "type": "ping",
        "sent_at": moment.isoformat(),
        "client": client_info(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _envelope(batch: tuple[Any, ...], now: datetime, items: dict[str, Any] | None = None) -> bytes:
    payload = {
        "schema": SCHEMA_VERSION,
        "type": "actions",
        "batch_id": f"b-{secrets.token_hex(4)}",
        "sent_at": now.isoformat(),
        "client": client_info(),
        "actions": [_action_row(action, _known_item(items, action.item)) for action in batch],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _known_item(items: dict[str, Any] | None, key: str) -> Any:
    if items is None:
        return None
    return items.get(key)


def _item_index(ctx: Any) -> dict[str, Any]:
    store = getattr(ctx, "store", None)
    if store is None:
        return {}
    return {item.key: item for item in store.items()}


def _action_row(action: Any, item: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "action": action.action,
        "action_id": action.action_id,
        "args": action.args,
        "created": action.created,
        "item": action.item,
    }
    if item is not None:
        title = getattr(item, "title", None)
        kind = getattr(item, "kind", None)
        if isinstance(title, str) and title:
            row["title"] = title
        if isinstance(kind, str) and kind:
            row["kind"] = kind
    return row


def _resolve_closed(ctx: Any, batch: tuple[Any, ...]) -> None:
    store = getattr(ctx, "store", None)
    if store is None:
        return
    changed = store.resolve_batch(list(batch))
    _publish_closed(ctx, changed)


def _release_closed(ctx: Any, action_ids: list[str]) -> None:
    store = getattr(ctx, "store", None)
    if store is None:
        return
    changed = store.release_actions(action_ids)
    _publish_closed(ctx, changed)


def _publish_closed(ctx: Any, changed: list[str]) -> None:
    if not changed:
        return
    api = getattr(ctx, "api", None)
    if api is not None:
        api.emit_items_changed([], changed, [])
    poller = getattr(ctx, "poller", None)
    if poller is not None and hasattr(poller, "request_state_write"):
        poller.request_state_write()


def _notify_body(plan: Plan) -> str:
    if plan.title == "Re-paste key":
        return "Bot details, Routines, the routine, Webhook, key"
    return plan.detail


def _backoff(attempts: int) -> int:
    index = min(max(attempts, 1), len(_BACKOFF_SECONDS)) - 1
    return _BACKOFF_SECONDS[index]


def _default_jitter(delay: int) -> float:
    if delay <= 0:
        return 0
    return random.uniform(0, delay * 0.1)


def _hold(rows: list[Any]) -> datetime | None:
    moments = [moment for moment in (_retry_at(row.detail) for row in rows) if moment is not None]
    if not moments:
        return None
    return max(moments)


def _retry_at(detail: str) -> datetime | None:
    for prefix in (_TIMEOUT_PREFIX, _RETRY_PREFIX):
        if detail.startswith(prefix):
            try:
                parsed = parse_iso8601(detail[len(prefix) :], field_name="retry-after")
                return parsed.astimezone(UTC)
            except ValueError:
                return None
    return None


def _discard(response: object) -> None:
    read = getattr(response, "read", None)
    if read is None:
        return
    try:
        read(2048)
    except Exception:
        return

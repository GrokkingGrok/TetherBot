# SPDX-License-Identifier: GPL-2.0-or-later
"""Bridge process.

Loads config, the item cache, and the action queue, then runs a main loop
until asked to stop. A GLib loop also owns the session bus name, opens the
secret service, and ticks ``webhook-sender`` when that adapter is enabled.
Other adapters and sinks are not started here.
"""

from __future__ import annotations

import logging
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TextIO

from tetherbot.config import BridgeConfig, ConfigError, QueueConfig, load_config
from tetherbot.dbus_service import STATES
from tetherbot.files import ensure_private_dir
from tetherbot.log import configure_logging
from tetherbot.queue import ActionQueue
from tetherbot.secrets import SecretStore, UnavailableBackend, open_secret_store
from tetherbot.service import BridgeApi
from tetherbot.store import ItemStore


class MainLoop(Protocol):
    """The process loop. Production uses GLib; tests pass a fake."""

    def run(self) -> None:
        """Block until ``quit``."""

    def quit(self) -> None:
        """Make ``run`` return."""

    def watch_unix_signals(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` once for SIGINT or SIGTERM."""


@dataclass(frozen=True)
class DaemonStatus:
    state: str
    reason: str
    running: bool
    mode: str | None
    queue_length: int
    config_path: Path
    state_dir: Path


class BridgeDaemon:
    """One user-session bridge. Constructing it does not touch the disk."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        state_dir: Path | None = None,
        loop: MainLoop | None = None,
        log_stream: TextIO | None = None,
        clock: Callable[[], datetime] | None = None,
        secrets: SecretStore | None = None,
        webhook_post: Callable[..., object] | None = None,
        webhook_online: Callable[[], bool] | None = None,
        webhook_jitter: Callable[[int], float] | None = None,
    ) -> None:
        self.config_path = default_config_path() if config_path is None else config_path
        self.state_dir = default_state_dir() if state_dir is None else state_dir
        self._loop = loop
        self._log_stream = log_stream
        self._clock = clock or (lambda: datetime.now(UTC))
        self.config: BridgeConfig | None = None
        self.store: ItemStore | None = None
        self.queue: ActionQueue | None = None
        self.state = "unconfigured"
        self.reason = "not started"
        self.running = False
        self._started = False
        self.api: BridgeApi | None = None
        self._secrets_explicit = secrets is not None
        self.secrets = secrets if secrets is not None else SecretStore(UnavailableBackend())
        self._webhook_post = webhook_post
        self._webhook_online = webhook_online
        self._webhook_jitter = webhook_jitter
        self.webhook = None
        self.base_state = self.state
        self.base_reason = self.reason

    def start(self) -> DaemonStatus:
        """Open state files and mark the process running. Does not block."""

        if self._started:
            raise RuntimeError("daemon already started")
        ensure_private_dir(self.state_dir)
        configure_logging(stream=self._log_stream, path=self.state_dir / "bridge.log")
        self._open()
        self._started = True
        self.running = True
        logging.getLogger("tetherbot").info("bridge %s: %s", self.state, self.reason)
        return self.status()

    def now(self) -> datetime:
        return self._clock()

    def _apply_keyring_state(self) -> None:
        try:
            status = self.secrets.status()
        except Exception:
            logging.getLogger("tetherbot").error("secret service is not available")
            return
        if status not in {"locked", "missing"} or self.base_state == "failed_closed":
            return
        self.base_state = "degraded"
        self.base_reason = "keyring locked"
        self._apply_overlay()
        if self.api is not None:
            self.api.publish_state()

    def reload_config(self) -> None:
        """Re-read ``config.toml`` and recompute the bridge state."""

        if not self._started or self.store is None or self.queue is None:
            raise RuntimeError("daemon is not started")
        config_error: str | None = None
        if self.config_path.is_file():
            try:
                self.config = load_config(self.config_path)
            except ConfigError as exc:
                self.config = None
                config_error = str(exc)
        else:
            self.config = None
        self._assign_base(
            *_decide_state(
                self.config,
                config_error,
                self.store.load_error,
                queue_unreadable=bool(self.queue.errors),
                config_exists=self.config_path.is_file(),
            )
        )
        self._sync_webhook()

    def run(self, *, install_signals: bool = False) -> int:
        """Start, then block in the main loop until ``stop``.

        A GLib loop claims the session bus name before it blocks. If that
        name is already owned, the process stops and returns 1.
        """

        if self._loop is None:
            self._loop = GLibMainLoop()
        if not self._started:
            self.start()
        export = None
        code = 0
        try:
            if isinstance(self._loop, GLibMainLoop):
                if not self._secrets_explicit:
                    self.secrets = open_secret_store()
                    self._apply_keyring_state()
                from tetherbot.dbus_service import BusOwnershipError, SessionExport

                export = SessionExport(self.api)
                try:
                    export.acquire()
                except BusOwnershipError:
                    self.state = "failed_closed"
                    self.reason = "bus name is already owned"
                    logging.getLogger("tetherbot").error(
                        "bridge failed_closed: bus name is already owned"
                    )
                    code = 1
                    return code
            if install_signals:
                self._loop.watch_unix_signals(self.stop)
            if hasattr(self._loop, "timeout_add"):
                self._loop.timeout_add(1, self.tick_webhook)
            self._loop.run()
        finally:
            if export is not None:
                export.release()
            if self.running:
                self.stop()
        return code

    def stop(self) -> None:
        """Leave the main loop. A second call does nothing."""

        if not self.running:
            return
        self.running = False
        if self.webhook is not None:
            self.webhook.stop()
            self.webhook = None
        logging.getLogger("tetherbot").info("bridge stopping")
        if self._loop is not None:
            self._loop.quit()

    def status(self) -> DaemonStatus:
        if self.state not in STATES:
            raise RuntimeError(f"unknown bridge state {self.state}")
        return DaemonStatus(
            state=self.state,
            reason=self.reason,
            running=self.running,
            mode=None if self.config is None else self.config.mode,
            queue_length=0 if self.queue is None else self.queue.pending_count(),
            config_path=self.config_path,
            state_dir=self.state_dir,
        )

    def _open(self) -> None:
        self.store = ItemStore(self.state_dir / "items.json")
        config_error: str | None = None
        if self.config_path.is_file():
            try:
                self.config = load_config(self.config_path)
            except ConfigError as exc:
                self.config = None
                config_error = str(exc)
        else:
            self.config = None
        limits = self.config.queue if self.config is not None else QueueConfig()
        self.queue = ActionQueue(
            self.state_dir / "queue",
            coalesce_seconds=limits.coalesce_seconds,
            coalesce_max_seconds=limits.coalesce_max_seconds,
            min_interval_seconds=limits.min_interval_seconds,
            daily_cap=limits.daily_cap,
        )
        cache_error = self.store.load_error
        if cache_error is None:
            self.store.refresh(self._clock())
        self._assign_base(
            *_decide_state(
                self.config,
                config_error,
                cache_error,
                queue_unreadable=bool(self.queue.errors),
                config_exists=self.config_path.is_file(),
            )
        )
        self.api = BridgeApi(self)
        self._sync_webhook()

    def tick_webhook(self) -> None:
        sender = self.webhook
        if sender is not None and self.running:
            sender.tick()

    def publish_overlay(self) -> None:
        self._apply_overlay()
        if self.api is not None:
            self.api.publish_state()

    @property
    def loop(self) -> MainLoop | None:
        return self._loop

    def _assign_base(self, state: str, reason: str) -> None:
        self.base_state = state
        self.base_reason = reason
        self._apply_overlay()

    def _apply_overlay(self) -> None:
        state, reason = self.base_state, self.base_reason
        overlay = None if self.webhook is None else self.webhook.overlay
        if overlay is not None and state == "ok":
            state, reason = overlay
        self.state = state
        self.reason = reason

    def _sync_webhook(self) -> None:
        enabled = False
        if self.config is not None:
            row = self.config.adapters.get("webhook-sender")
            enabled = row is not None and row.enabled
        if enabled and self.webhook is None:
            from tetherbot.adapters.webhook_sender import WebhookSender

            kwargs: dict[str, object] = {}
            if self._webhook_post is not None:
                kwargs["post"] = self._webhook_post
            if self._webhook_online is not None:
                kwargs["online"] = self._webhook_online
            if self._webhook_jitter is not None:
                kwargs["jitter"] = self._webhook_jitter
            self.webhook = WebhookSender(**kwargs)
            self.webhook.start(self)
        elif not enabled and self.webhook is not None:
            self.webhook.stop()
            self.webhook = None
        self._apply_overlay()


class GLibMainLoop:
    """GLib main loop. Importing this module does not import PyGObject."""

    def __init__(self) -> None:
        try:
            import gi

            gi.require_version("GLib", "2.0")
            from gi.repository import GLib
        except (ImportError, ValueError) as exc:
            raise ImportError("PyGObject GLib is not available") from exc
        self._glib = GLib
        self._loop = GLib.MainLoop()

    def run(self) -> None:
        self._loop.run()

    def quit(self) -> None:
        self._loop.quit()

    def timeout_add(self, seconds: int, callback: Callable[[], None]) -> None:
        def _wrapped() -> bool:
            callback()
            return True

        self._glib.timeout_add_seconds(max(seconds, 1), _wrapped)

    def idle_add(self, callback: Callable[[], None]) -> None:
        def _wrapped() -> bool:
            callback()
            return False

        self._glib.idle_add(_wrapped)

    def watch_unix_signals(self, callback: Callable[[], None]) -> None:
        def _wrapped() -> bool:
            callback()
            return False

        priority = self._glib.PRIORITY_DEFAULT
        self._glib.unix_signal_add(priority, signal.SIGTERM, _wrapped)
        self._glib.unix_signal_add(priority, signal.SIGINT, _wrapped)


def default_config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "tetherbot" / "config.toml"


def default_state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "tetherbot"


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else fallback


_IMPLEMENTED = frozenset({"webhook-sender"})


def _decide_state(
    config: BridgeConfig | None,
    config_error: str | None,
    cache_error: str | None,
    *,
    queue_unreadable: bool,
    config_exists: bool,
) -> tuple[str, str]:
    if config_error is not None:
        return "failed_closed", config_error
    if cache_error is not None:
        return "degraded", cache_error
    if queue_unreadable:
        return "degraded", "action queue has unreadable files"
    if not config_exists or config is None:
        return "unconfigured", "config.toml is missing"
    enabled = sorted(
        name
        for table in (config.adapters, config.sinks)
        for name, row in table.items()
        if row.enabled
    )
    if not enabled:
        return "unconfigured", "no adapter is enabled"
    pending = [name for name in enabled if name not in _IMPLEMENTED]
    if pending:
        return "degraded", "not started: " + ", ".join(pending)
    return "ok", ""

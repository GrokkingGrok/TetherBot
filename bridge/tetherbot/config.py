# SPDX-License-Identifier: GPL-2.0-or-later
"""Load ``config.toml``.

Secrets are rejected. Adapters stay disabled unless the file enables them
by name. An unknown schema major fails closed.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from tetherbot.files import write_private_text
from tetherbot.model import looks_like_secret
from tetherbot.queue import (
    DEFAULT_COALESCE_MAX_SECONDS,
    DEFAULT_COALESCE_SECONDS,
    DEFAULT_DAILY_CAP,
    DEFAULT_MIN_INTERVAL_SECONDS,
    _check_limits,
)
from tetherbot.version_gate import check_schema

MODES = frozenset({"webhook-only", "repo-only", "full"})
_ADAPTERS = frozenset({"webhook-sender", "github-poller", "official"})
_FORBIDDEN_KEYS = frozenset(
    {"key", "token", "password", "secret", "authorization", "webhook_url", "webhook_key"}
)
_SLOT = re.compile(r"^[a-z0-9-]{1,64}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")


class ConfigError(ValueError):
    """The config file was refused. The message does not contain secret text."""


@dataclass(frozen=True)
class AdapterConfig:
    enabled: bool
    remote: str | None = None
    branch: str | None = None
    poll_seconds: int | None = None
    auth: str | None = None


@dataclass(frozen=True)
class SinkConfig:
    enabled: bool
    mode: str = "shadow"
    todo_path: str = ""
    previous_unit: str = ""


@dataclass(frozen=True)
class BotConfig:
    webhook_slot: str


@dataclass(frozen=True)
class QueueConfig:
    coalesce_seconds: int = DEFAULT_COALESCE_SECONDS
    coalesce_max_seconds: int = DEFAULT_COALESCE_MAX_SECONDS
    min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS
    daily_cap: int = DEFAULT_DAILY_CAP


@dataclass(frozen=True)
class BridgeConfig:
    schema: str
    mode: str
    adapters: Mapping[str, AdapterConfig]
    sinks: Mapping[str, SinkConfig]
    bots: Mapping[str, BotConfig]
    queue: QueueConfig
    path: Path | None = None


def load_config(path: Path) -> BridgeConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config ({exc.__class__.__name__})") from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config is not valid TOML") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config must be a table")
    _reject_secrets(raw, "")
    schema = raw.get("schema")
    decision = check_schema(schema, source=path.name)
    if not decision.accepted:
        raise ConfigError(decision.message)
    if not isinstance(schema, str):
        raise ConfigError("schema must be a string")
    bridge = raw.get("bridge", {})
    if not isinstance(bridge, dict):
        raise ConfigError("bridge must be a table")
    mode = bridge.get("mode", "webhook-only")
    if mode not in MODES:
        raise ConfigError("bridge.mode must be webhook-only, repo-only, or full")
    return BridgeConfig(
        schema=schema,
        mode=mode,
        adapters=_adapters(raw.get("adapters", {})),
        sinks=_sinks(raw.get("sinks", {})),
        bots=_bots(raw.get("bots", {})),
        queue=_queue(raw.get("queue", {})),
        path=path,
    )


def _adapters(raw: object) -> dict[str, AdapterConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("adapters must be a table")
    parsed: dict[str, AdapterConfig] = {}
    for name, table in raw.items():
        if name not in _ADAPTERS:
            raise ConfigError(f"unknown adapter {name}")
        if not isinstance(table, dict):
            raise ConfigError(f"adapters.{name} must be a table")
        enabled = table.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError(f"adapters.{name}.enabled must be a boolean")
        remote = table.get("remote")
        branch = table.get("branch")
        poll = table.get("poll_seconds")
        auth = table.get("auth")
        if remote is not None:
            remote = _remote(str(name), remote, auth if isinstance(auth, str) else None)
        if branch is not None and (
            not isinstance(branch, str) or _BRANCH.fullmatch(branch) is None
        ):
            raise ConfigError(f"adapters.{name}.branch is invalid")
        if poll is not None and (
            isinstance(poll, bool) or not isinstance(poll, int) or not 60 <= poll <= 900
        ):
            raise ConfigError(f"adapters.{name}.poll_seconds must be from 60 to 900")
        if auth is not None and auth not in {"https-token", "ssh-deploy-key"}:
            raise ConfigError(f"adapters.{name}.auth must be https-token or ssh-deploy-key")
        parsed[name] = AdapterConfig(
            enabled=enabled,
            remote=remote if isinstance(remote, str) else None,
            branch=branch if isinstance(branch, str) else None,
            poll_seconds=poll if isinstance(poll, int) else None,
            auth=auth if isinstance(auth, str) else None,
        )
    return parsed


def _remote(name: str, remote: object, auth: str | None) -> str:
    if not isinstance(remote, str) or not remote:
        raise ConfigError(f"adapters.{name}.remote must be a URL")
    if auth == "ssh-deploy-key":
        if not remote.startswith("git@github.com:"):
            raise ConfigError(f"adapters.{name}.remote must be a git@github.com path")
        return remote
    parts = urlsplit(remote)
    if parts.username or parts.password:
        raise ConfigError(f"adapters.{name}.remote must be an https URL without credentials")
    if parts.scheme == "file" and name == "github-poller":
        if parts.netloc not in {"", "localhost"} or not parts.path.startswith("/"):
            raise ConfigError(f"adapters.{name}.remote must be a file URL with an absolute path")
        return remote
    if parts.scheme != "https" or not parts.netloc:
        raise ConfigError(f"adapters.{name}.remote must be an https URL without credentials")
    return remote


def _sinks(raw: object) -> dict[str, SinkConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("sinks must be a table")
    parsed: dict[str, SinkConfig] = {}
    for name, table in raw.items():
        if name != "legacy-todo":
            raise ConfigError(f"unknown sink {name}")
        if not isinstance(table, dict):
            raise ConfigError("sinks.legacy-todo must be a table")
        enabled = table.get("enabled", False)
        mode = table.get("mode", "shadow")
        if not isinstance(enabled, bool):
            raise ConfigError("sinks.legacy-todo.enabled must be a boolean")
        if mode not in {"shadow", "live"}:
            raise ConfigError("sinks.legacy-todo.mode must be shadow or live")
        todo_path = table.get("todo_path", "")
        previous = table.get("previous_unit", "")
        if not isinstance(todo_path, str) or not isinstance(previous, str):
            raise ConfigError("sink paths must be strings")
        parsed[name] = SinkConfig(
            enabled=enabled,
            mode=mode,
            todo_path=todo_path,
            previous_unit=previous,
        )
    return parsed


def _bots(raw: object) -> dict[str, BotConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("bots must be a table")
    parsed: dict[str, BotConfig] = {}
    for name, table in raw.items():
        if _SLOT.fullmatch(str(name)) is None:
            raise ConfigError("bot names must match [a-z0-9-]{1,64}")
        if not isinstance(table, dict):
            raise ConfigError(f"bots.{name} must be a table")
        slot = table.get("webhook_slot")
        if not isinstance(slot, str) or _SLOT.fullmatch(slot) is None:
            raise ConfigError(f"bots.{name}.webhook_slot must match [a-z0-9-]{1,64}")
        parsed[str(name)] = BotConfig(webhook_slot=slot)
    return parsed


def _queue(raw: object) -> QueueConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("queue must be a table")
    values = {
        "coalesce_seconds": DEFAULT_COALESCE_SECONDS,
        "coalesce_max_seconds": DEFAULT_COALESCE_MAX_SECONDS,
        "min_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS,
        "daily_cap": DEFAULT_DAILY_CAP,
    }
    for name in values:
        if name not in raw:
            continue
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"queue.{name} must be an integer")
        values[name] = value
    try:
        _check_limits(
            values["coalesce_seconds"],
            values["coalesce_max_seconds"],
            values["min_interval_seconds"],
            values["daily_cap"],
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return QueueConfig(**values)


def _reject_secrets(value: object, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                where = f"{path}.{key}" if path else str(key)
                raise ConfigError(f"{where} is not allowed in config")
            child_path = f"{path}.{key}" if path else str(key)
            _reject_secrets(child, child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
        return
    if isinstance(value, str) and looks_like_secret(value):
        raise ConfigError(f"{path} looks like a secret")


def save_adapter_enabled(path: Path, name: str, enabled: bool) -> None:
    """Set one adapter's ``enabled`` flag and leave the rest of the file in place.

    The file is rewritten only when the result still loads. A refused result
    restores the previous text.
    """

    if name not in _ADAPTERS:
        raise ConfigError(f"unknown adapter {name}")
    if not isinstance(enabled, bool):
        raise ConfigError("enabled must be a boolean")
    if not path.is_file():
        raise ConfigError("config.toml is missing")
    original = path.read_text(encoding="utf-8")
    updated = _rewrite_enabled(original, f"adapters.{name}", enabled)
    write_private_text(path, updated)
    try:
        load_config(path)
    except ConfigError:
        write_private_text(path, original)
        raise


def _rewrite_enabled(text: str, section: str, enabled: bool) -> str:
    header = f"[{section}]"
    flag = "true" if enabled else "false"
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        base = text if text.endswith("\n") or text == "" else text + "\n"
        if base and not base.endswith("\n\n"):
            base += "\n" if base.endswith("\n") else ""
        return f"{base}{header}\nenabled = {flag}\n"
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    for index in range(start + 1, end):
        stripped = lines[index].lstrip()
        if stripped.startswith("#"):
            continue
        if re.match(r"enabled\s*=", stripped):
            lines[index] = f"enabled = {flag}"
            return "\n".join(lines) + "\n"
    lines.insert(start + 1, f"enabled = {flag}")
    return "\n".join(lines) + "\n"

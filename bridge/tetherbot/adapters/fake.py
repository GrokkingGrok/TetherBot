# SPDX-License-Identifier: GPL-2.0-or-later
"""In-process adapter for tests and demos.

Reads JSON fixtures, or returns no items when no directory is set.
``send`` records batches. This adapter does not open a network connection.

A future debug D-Bus method may inject events. That method exists only
when the daemon is started with ``--debug``, which is not implemented yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult
from tetherbot.model import Item
from tetherbot.version_gate import check_schema


class FakeAdapter:
    name = "fake"
    direction = frozenset({"inbound", "outbound"})

    def __init__(
        self,
        fixtures: Path | None = None,
        *,
        response_status: str = "accepted",
    ) -> None:
        self.fixtures = fixtures
        self.response_status = response_status
        self.sent: list[tuple[str, list[Any]]] = []
        self._ctx: object | None = None
        self._running = False

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._ctx = None

    def poll(self) -> PollResult:
        if self.fixtures is None:
            return PollResult(items=[])
        items: list[Item] = []
        errors: list[str] = []
        stale: list[str] = []
        for path in sorted(self.fixtures.glob("*.json")):
            parsed, error = _read_fixture(path)
            if error is not None:
                errors.append(error)
                stale.append(path.name)
                continue
            items.extend(parsed)
        return PollResult(items=items, errors=errors, stale_sources=stale)

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        self.sent.append((bot, list(batch)))
        return SendResult(status=self.response_status, detail="recorded")

    def status(self) -> AdapterStatus:
        state = "ok" if self._running else "stopped"
        return AdapterStatus(name=self.name, enabled=True, state=state, detail="")


def _read_fixture(path: Path) -> tuple[list[Item], str | None]:
    source = path.name
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{source}: unreadable ({exc.__class__.__name__})"
    if not isinstance(payload, dict):
        decision_message = f"{source}: unsupported schema, update tetherbot"
        return [], decision_message
    decision = check_schema(payload.get("schema"), source=source)
    if not decision.accepted:
        return [], decision.message
    bot = payload.get("bot")
    if not isinstance(bot, str) or not bot:
        return [], f"{source}: missing bot"
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return [], f"{source}: items must be a list"
    try:
        parsed = [Item.from_mapping(entry, bot=bot, origin="fake") for entry in raw_items]
    except (TypeError, ValueError) as exc:
        return [], f"{source}: {exc}"
    return parsed, None

# SPDX-License-Identifier: GPL-2.0-or-later
"""Placeholder for a future official Grok Bot API, SDK, or desktop hook.

Enabling this adapter before an implementation exists reports
``unavailable: no official API known``. It takes priority over
``github-poller`` for the same bot only after a real implementation ships.
"""

from __future__ import annotations

from typing import Any

from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult

_DETAIL = "no official API known"


class OfficialAdapter:
    name = "official"
    direction = frozenset({"inbound", "outbound"})

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx

    def stop(self) -> None:
        self._ctx = None

    def poll(self) -> PollResult:
        return PollResult(items=[], errors=[_DETAIL])

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        del bot, batch
        return SendResult(status="unavailable", detail=_DETAIL)

    def status(self) -> AdapterStatus:
        return AdapterStatus(name=self.name, enabled=False, state="unavailable", detail=_DETAIL)

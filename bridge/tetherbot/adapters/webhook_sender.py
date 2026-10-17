# SPDX-License-Identifier: GPL-2.0-or-later
"""Outbound webhook adapter stub.

TODO(v0.1): POST action envelopes to a routine webhook. The URL and key
stay in the secret service. This module must not log either value.
"""

from __future__ import annotations

from typing import Any

from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult


class WebhookSender:
    name = "webhook-sender"
    direction = frozenset({"outbound"})

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx

    def stop(self) -> None:
        self._ctx = None

    def poll(self) -> PollResult:
        return PollResult(items=[], errors=["webhook-sender is outbound only"])

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        del bot, batch
        return SendResult(status="unavailable", detail="webhook-sender is not implemented")

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            name=self.name,
            enabled=False,
            state="unavailable",
            detail="not implemented",
        )

# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional inbound poller and write-back stub for a private git repo.

TODO(v0.1): poll a configured repo and write only paths this bridge owns.
The credential must come from a git credential helper backed by the secret
service. It must not appear in a URL, argv, an environment variable, or a log.
"""

from __future__ import annotations

from typing import Any

from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult


class GitHubPoller:
    name = "github-poller"
    direction = frozenset({"inbound", "outbound"})

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx

    def stop(self) -> None:
        self._ctx = None

    def poll(self) -> PollResult:
        return PollResult(items=[], errors=["github-poller is not implemented"])

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        del bot, batch
        return SendResult(status="unavailable", detail="github-poller is not implemented")

    def status(self) -> AdapterStatus:
        return AdapterStatus(
            name=self.name,
            enabled=False,
            state="unavailable",
            detail="not implemented",
        )

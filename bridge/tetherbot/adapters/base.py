# SPDX-License-Identifier: GPL-2.0-or-later
"""Transport adapter interface.

Every adapter is off until enabled in config. Adapter code must never log
a secret, a URL that contains a key, or an Authorization header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tetherbot.model import Item


@dataclass
class PollResult:
    items: list[Item]
    errors: list[str] = field(default_factory=list)
    stale_sources: list[str] = field(default_factory=list)


@dataclass
class SendResult:
    status: str
    detail: str = ""


@dataclass
class AdapterStatus:
    name: str
    enabled: bool
    state: str
    detail: str = ""


class Adapter(Protocol):
    """Inbound poll, outbound send, or both. ``direction`` is a subset of those."""

    name: str
    direction: frozenset[str]

    def start(self, ctx: object | None = None) -> None:
        """Start background work. ``ctx`` will grow store, queue, secrets, and log."""

    def stop(self) -> None:
        """Release resources held by ``start``."""

    def poll(self) -> PollResult:
        """Read inbound items. Outbound-only adapters return an error result."""

    def send(self, bot: str, batch: list[Any]) -> SendResult:
        """Deliver one outbound batch for ``bot``."""

    def status(self) -> AdapterStatus:
        """Return a secret-free status snapshot."""

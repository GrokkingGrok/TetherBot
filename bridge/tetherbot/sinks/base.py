# SPDX-License-Identifier: GPL-2.0-or-later
"""Sink interface.

Sinks see the item snapshot after each inbound poll. A sink that writes
back through a repo goes through the adapter that owns that repo.
"""

from __future__ import annotations

from typing import Protocol


class Sink(Protocol):
    name: str

    def start(self, ctx: object | None = None) -> None:
        """Prepare the sink. It stays idle until config enables it."""

    def stop(self) -> None:
        """Release resources held by ``start``."""

    def on_items(self, snapshot: object, diff: object) -> None:
        """Apply one store update. ``snapshot`` and ``diff`` are defined later."""

# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared builders for protocol objects in unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tetherbot.model import Item

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "sample-01",
        "kind": "ask",
        "title": "Approve the sample",
        "body": "Details",
        "status": "open",
        "created": "2026-10-17T11:40:00+00:00",
        "updated_at": "2026-10-17T11:40:00+00:00",
        "notify": True,
        "actions": ["approve"],
        "source": {"bot": "primary"},
    }
    data.update(overrides)
    return data


def make_item(**overrides: Any) -> Item:
    bot = overrides.pop("bot", "primary")
    origin = overrides.pop("origin", "feed")
    return Item.from_mapping(payload(**overrides), bot=bot, origin=origin)

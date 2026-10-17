# SPDX-License-Identifier: GPL-2.0-or-later
"""Item and action-envelope models.

Field rules live in docs/PROTOCOL.md. This scaffold preserves unknown
fields. Length limits, id patterns, and the secret guard are still TODO.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def global_key(bot: str, item_id: str) -> str:
    """Return the in-bridge key ``<bot>/<id>``."""

    return f"{bot}/{item_id}"


@dataclass
class Item:
    id: str
    kind: str
    title: str
    bot: str
    status: str = "open"
    body: str = ""
    origin: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return global_key(self.bot, self.id)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, bot: str, origin: str) -> Item:
        """Build an item. Unknown fields are kept on ``extra``."""

        if not isinstance(data, Mapping):
            raise TypeError("item must be an object")
        item_id = data.get("id")
        kind = data.get("kind")
        title = data.get("title")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("item id is required")
        if not isinstance(kind, str) or not kind:
            raise ValueError("item kind is required")
        if not isinstance(title, str) or not title:
            raise ValueError("item title is required")
        known = {"id", "kind", "title", "status", "body"}
        extra = {key: value for key, value in data.items() if key not in known}
        status = data.get("status", "open")
        body = data.get("body", "")
        if not isinstance(status, str):
            raise ValueError("item status must be a string")
        if not isinstance(body, str):
            raise ValueError("item body must be a string")
        return cls(
            id=item_id,
            kind=kind,
            title=title,
            bot=bot,
            status=status,
            body=body,
            origin=origin,
            extra=extra,
        )


@dataclass
class ActionEnvelope:
    """Desktop-to-bot batch. The webhook key never belongs in this body."""

    schema: str
    type: str
    batch_id: str
    sent_at: str
    actions: list[dict[str, Any]]
    client: dict[str, Any] = field(default_factory=dict)

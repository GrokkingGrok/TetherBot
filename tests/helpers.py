# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared builders for protocol objects in unit tests."""

from __future__ import annotations

import logging
import sys
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


def reset_tetherbot_logger() -> None:
    """Return the bridge logger to the state unit tests assume.

    ``configure_logging`` stops propagation and replaces handlers, and
    importing GTK can disable loggers. ``caplog`` does not see a record
    when the logger is disabled, filtered out, or no longer propagating
    to the root handler it already installed.
    """

    logger = logging.getLogger("tetherbot")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        if type(handler).__module__.startswith("_pytest"):
            continue
        stream = getattr(handler, "stream", None)
        if stream is sys.stderr or stream is sys.stdout:
            continue
        try:
            handler.close()
        except OSError:
            pass
    for filt in list(logger.filters):
        logger.removeFilter(filt)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    logger.disabled = False
    logging.disable(logging.NOTSET)

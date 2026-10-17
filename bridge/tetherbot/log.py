# SPDX-License-Identifier: GPL-2.0-or-later
"""Logging with a redaction filter.

The filter masks secret-shaped patterns and any exact secret values the
caller is holding. It does not write those values to the handler.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TextIO

from tetherbot.model import mask_secrets


class RedactingFilter(logging.Filter):
    def __init__(self, extra_secrets: Sequence[str] = ()) -> None:
        super().__init__()
        self._extra = tuple(secret for secret in extra_secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.msg = record.msg % record.args
            record.args = ()
        record.msg = mask_secrets(str(record.msg), self._extra)
        if record.exc_text:
            record.exc_text = mask_secrets(record.exc_text, self._extra)
        return True


def configure_logging(
    level: int = logging.INFO,
    *,
    stream: TextIO | None = None,
    extra_secrets: Sequence[str] = (),
) -> logging.Logger:
    """Attach one redacting handler to the ``tetherbot`` logger."""

    logger = logging.getLogger("tetherbot")
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter(extra_secrets))
    logger.addHandler(handler)
    logger.propagate = False
    return logger

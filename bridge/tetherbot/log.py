# SPDX-License-Identifier: GPL-2.0-or-later
"""Logging with a redaction filter.

The filter masks secret-shaped patterns and any exact secret values the
caller is holding. It does not write those values to the handler.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
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
    path: Path | None = None,
    extra_secrets: Sequence[str] = (),
) -> logging.Logger:
    """Attach redacting handlers to the ``tetherbot`` logger.

    ``stream`` is the journal when the process runs under systemd. ``path``
    is ``bridge.log`` in the state directory. A previous handler is closed.
    """

    logger = logging.getLogger("tetherbot")
    logger.setLevel(level)
    for old in list(logger.handlers):
        logger.removeHandler(old)
        old.close()
    logger.addHandler(_handler(logging.StreamHandler(stream), extra_secrets))
    if path is not None:
        file_handler = logging.FileHandler(path, encoding="utf-8")
        os.chmod(path, 0o600)
        logger.addHandler(_handler(file_handler, extra_secrets))
    logger.propagate = False
    return logger


def _handler(handler: logging.Handler, extra_secrets: Sequence[str]) -> logging.Handler:
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter(extra_secrets))
    return handler

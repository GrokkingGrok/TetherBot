# SPDX-License-Identifier: GPL-2.0-or-later
"""Redacting log handler."""

import logging
from io import StringIO

from tetherbot.log import configure_logging
from tetherbot.model import SECRET_REPLACEMENT


def test_log_masks_patterns_and_exact_secrets():
    stream = StringIO()
    secret = "session-token-value"
    logger = logging.getLogger("tetherbot")
    previous = logger.propagate
    try:
        configured = configure_logging(stream=stream, extra_secrets=(secret,))
        configured.info("sent Bearer %s for %s", "super-secret", "primary")
        configured.info("stored %s", secret)
        configured.info("bot primary is idle")
        text = stream.getvalue()
        assert "super-secret" not in text
        assert secret not in text
        assert SECRET_REPLACEMENT in text
        assert "bot primary is idle" in text
        assert logger.propagate is False
    finally:
        logger.handlers.clear()
        logger.propagate = previous

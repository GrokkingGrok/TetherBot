# SPDX-License-Identifier: GPL-2.0-or-later
"""Redacting log handler."""

import logging
import stat
from io import StringIO
from pathlib import Path

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
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = previous


def test_log_file_is_private_and_redacted(tmp_path: Path):
    path = tmp_path / "bridge.log"
    stream = StringIO()
    logger = logging.getLogger("tetherbot")
    previous = logger.propagate
    try:
        configured = configure_logging(stream=stream, path=path)
        configured.info("bearer ghp_abcdefghijklmnopqrstuvwxyz")
        text = path.read_text(encoding="utf-8")
        assert "ghp_" not in text
        assert "ghp_" not in stream.getvalue()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = previous

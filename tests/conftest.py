# SPDX-License-Identifier: GPL-2.0-or-later
"""Suite-wide fixtures."""

import pytest

from tests.helpers import reset_tetherbot_logger


@pytest.fixture(autouse=True)
def _isolate_tetherbot_logger():
    """Drop logger changes left by an earlier test or an import."""

    reset_tetherbot_logger()
    yield

# SPDX-License-Identifier: GPL-2.0-or-later
"""TetherBot bridge package.

Pre-alpha. Config loading, redacting logs, the item store, and the action
queue are implemented. The daemon process is not started yet.
"""

__version__ = "0.0.0"

SCHEMA_NAME = "tetherbot"
SCHEMA_MAJOR = 1
SCHEMA_VERSION = f"{SCHEMA_NAME}/{SCHEMA_MAJOR}"

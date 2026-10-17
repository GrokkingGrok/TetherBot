# SPDX-License-Identifier: GPL-2.0-or-later
"""TetherBot bridge package.

Pre-alpha. Config loading, redacting logs, the item store, the action
queue, and the daemon process are implemented. The process does not own
the D-Bus name and does not open the network.
"""

__version__ = "0.0.0"

SCHEMA_NAME = "tetherbot"
SCHEMA_MAJOR = 1
SCHEMA_VERSION = f"{SCHEMA_NAME}/{SCHEMA_MAJOR}"

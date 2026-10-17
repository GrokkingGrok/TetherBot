# SPDX-License-Identifier: GPL-2.0-or-later
"""TetherBot bridge package.

Pre-alpha. Config loading, redacting logs, the item store, the action
queue, the daemon process, and the session bus service are implemented.
The process does not read the secret service and does not open the network.
"""

__version__ = "0.0.0"

SCHEMA_NAME = "tetherbot"
SCHEMA_MAJOR = 1
SCHEMA_VERSION = f"{SCHEMA_NAME}/{SCHEMA_MAJOR}"

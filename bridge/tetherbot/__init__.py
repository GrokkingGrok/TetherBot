# SPDX-License-Identifier: GPL-2.0-or-later
"""TetherBot bridge package.

Pre-alpha. Config loading, redacting logs, the item store, the action
queue, the daemon process, the session bus service, secret-service
storage, and ``tetherbotctl`` are implemented. The bridge process does
not open the network. ``tetherbotctl webhook test`` can send one ping.
The key dialog is not built yet.
"""

__version__ = "0.0.0"

SCHEMA_NAME = "tetherbot"
SCHEMA_MAJOR = 1
SCHEMA_VERSION = f"{SCHEMA_NAME}/{SCHEMA_MAJOR}"

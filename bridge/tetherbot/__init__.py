# SPDX-License-Identifier: GPL-2.0-or-later
"""TetherBot bridge package.

Pre-alpha. Config loading, redacting logs, the item store, the action
queue, the daemon process, the session bus service, secret-service
storage, ``tetherbotctl``, ``webhook-sender``, and ``github-poller`` are
implemented. ``webhook-sender`` posts only when that adapter is enabled.
``github-poller`` runs git for a ``file://`` remote and, with
``git-credential-tetherbot``, for an ``https`` GitHub remote.
``ssh-deploy-key``, the key dialog, and ``repo setup`` are not built yet.
"""

__version__ = "0.0.0"

SCHEMA_NAME = "tetherbot"
SCHEMA_MAJOR = 1
SCHEMA_VERSION = f"{SCHEMA_NAME}/{SCHEMA_MAJOR}"

# SPDX-License-Identifier: GPL-2.0-or-later
"""Private JSON writes for bridge state.

Files are mode 0600. The write is fsynced, then the directory is fsynced,
so a crash does not leave an empty action or cache file behind.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` at mode 0700 without changing its parent."""

    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace ``path`` with ``payload`` and fsync it."""

    ensure_private_dir(path.parent)
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)

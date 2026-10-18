# SPDX-License-Identifier: GPL-2.0-or-later
"""Search local TetherBot files for a secret without reporting the value.

The manual check M13 uses this. Callers pass the secret in memory. The
report names only the category that matched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

_MAX_FILE = 20_000_000


def scan(
    secrets: Sequence[str],
    roots: Mapping[str, Path],
    *,
    journal: str = "",
    dconf: str = "",
) -> list[str]:
    """Return category names that contain any secret. The names are not values."""

    needles = [secret.encode("utf-8") for secret in secrets if secret]
    if not needles:
        return []
    hits: list[str] = []
    for name, root in roots.items():
        if _tree_contains(root, needles):
            hits.append(name)
    if _text_contains(journal, needles):
        hits.append("journal")
    if _text_contains(dconf, needles):
        hits.append("dconf")
    return hits


def report(hits: Sequence[str], skipped: Sequence[str] = ()) -> str:
    """A secret-free summary. ``hits`` are category names."""

    lines = [f"skipped: {name}" for name in skipped]
    if hits:
        lines.extend(f"match: {name}" for name in hits)
    else:
        lines.append("clean")
    return "\n".join(lines) + "\n"


def _tree_contains(root: Path, needles: Sequence[bytes]) -> bool:
    if not root.exists():
        return False
    if root.is_file():
        return _file_contains(root, needles)
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if _file_contains(path, needles):
            return True
    return False


def _file_contains(path: Path, needles: Sequence[bytes]) -> bool:
    try:
        if path.stat().st_size > _MAX_FILE:
            return False
        data = path.read_bytes()
    except OSError:
        return False
    return any(needle in data for needle in needles)


def _text_contains(text: str, needles: Sequence[bytes]) -> bool:
    if not text:
        return False
    data = text.encode("utf-8", errors="replace")
    return any(needle in data for needle in needles)

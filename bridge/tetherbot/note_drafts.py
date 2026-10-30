# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-todo note drafts on this machine.

The file sits next to clipboard history. A secret-looking note is not
stored. An unknown schema is left as it is.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tetherbot import SCHEMA_VERSION
from tetherbot.files import write_private_json
from tetherbot.model import looks_like_secret

_DRAFT_NAME = "note-drafts.json"


def note_drafts_path() -> Path:
    """``note-drafts.json`` under the XDG state directory."""

    raw = os.environ.get("XDG_STATE_HOME")
    base = Path(raw) if raw else Path.home() / ".local" / "state"
    return base / "tetherbot" / _DRAFT_NAME


def read_note_drafts(path: Path | None) -> tuple[dict[str, str], bool]:
    """Load drafts. The second value is whether this process may replace the file.

    A missing file and a corrupt file start empty and may be replaced.
    A schema this build does not know is not loaded and is not replaced.
    """

    if path is None or not path.is_file():
        return {}, True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, True
    if not isinstance(payload, dict):
        return {}, True
    schema = payload.get("schema")
    if schema != SCHEMA_VERSION:
        if isinstance(schema, str) and schema:
            return {}, False
        return {}, True
    raw = payload.get("drafts")
    if not isinstance(raw, dict):
        return {}, True
    drafts: dict[str, str] = {}
    for key, text in raw.items():
        if not isinstance(key, str) or not key or not isinstance(text, str):
            continue
        if not text.strip() or looks_like_secret(text):
            continue
        drafts[key] = text
    return drafts, True


def write_note_drafts(path: Path | None, drafts: dict[str, str], *, writable: bool) -> None:
    """Replace the file when this process owns it. An empty new file is not created."""

    if path is None or not writable:
        return
    if not drafts and not path.exists():
        return
    clean = {
        key: text
        for key, text in drafts.items()
        if isinstance(key, str) and key and isinstance(text, str) and text.strip()
        and not looks_like_secret(text)
    }
    write_private_json(path, {"schema": SCHEMA_VERSION, "drafts": clean})

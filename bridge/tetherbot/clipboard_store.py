# SPDX-License-Identifier: GPL-2.0-or-later
"""Local clipboard history.

The file is mode 0600 under the bridge state directory. Entries are not
written to the feed, the queue, or a log.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tetherbot.clipboard_policy import (
    CLIPBOARD_LIMIT_DEFAULT,
    DEFAULT_EXCLUDED_APPS,
    clamp_clipboard_limit,
    classify_clipboard,
    excluded_apps,
)
from tetherbot.files import write_private_json

_ID = re.compile(r"^c-[0-9a-f]{8}$")


class ClipboardHistory:
    """Newest-first plain-text history with a cap."""

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        limit: int = CLIPBOARD_LIMIT_DEFAULT,
        excluded: object = DEFAULT_EXCLUDED_APPS,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.path = path
        self.enabled = enabled is True
        self.limit = clamp_clipboard_limit(limit)
        self.excluded = excluded_apps(excluded)
        self._clock = clock or (lambda: int(time.time()))
        self.entries: list[dict[str, Any]] = []
        self.load()

    def configure(self, *, enabled: bool, limit: int, excluded: object) -> None:
        """Apply settings. A lower cap drops the oldest entries."""

        self.enabled = enabled is True
        self.limit = clamp_clipboard_limit(limit)
        self.excluded = excluded_apps(excluded)
        if len(self.entries) > self.limit:
            self.entries = self.entries[: self.limit]
            self.save()

    def offer(self, text: str, mimes: object, wm_class: object) -> str:
        """Store plain text, or return a skip reason. The text is not logged."""

        result = classify_clipboard(
            text,
            mimes,
            wm_class,
            enabled=self.enabled,
            excluded=self.excluded,
        )
        if result != "stored" or not isinstance(text, str):
            return result
        now = int(self._clock())
        current = next((row for row in self.entries if row["text"] == text), None)
        if current is None:
            entry = {"id": self._new_id(), "text": text, "at": now}
        else:
            entry = {"id": current["id"], "text": text, "at": now}
        self.entries = [entry, *[row for row in self.entries if row["id"] != entry["id"]]]
        if len(self.entries) > self.limit:
            self.entries = self.entries[: self.limit]
        self.save()
        return "stored"

    def list_entries(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.casefold().strip() if isinstance(query, str) else ""
        rows: list[dict[str, Any]] = []
        for row in self.entries:
            if needle and needle not in str(row["text"]).casefold():
                continue
            rows.append({"id": row["id"], "text": row["text"], "at": row["at"]})
        return rows

    def delete(self, entry_id: str) -> bool:
        if not isinstance(entry_id, str) or not _ID.fullmatch(entry_id):
            return False
        kept = [row for row in self.entries if row["id"] != entry_id]
        if len(kept) == len(self.entries):
            return False
        self.entries = kept
        self.save()
        return True

    def clear(self) -> bool:
        self.entries = []
        self.save()
        return True

    def load(self) -> None:
        if not self.path.is_file():
            self.entries = []
            return
        try:
            os.chmod(self.path, 0o600)
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            self.entries = []
            return
        rows = payload.get("entries") if isinstance(payload, dict) else None
        cleaned: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = row.get("text")
                ident = row.get("id")
                at = row.get("at")
                if (
                    not isinstance(text, str)
                    or not isinstance(ident, str)
                    or not _ID.fullmatch(ident)
                ):
                    continue
                if isinstance(at, bool) or not isinstance(at, int):
                    at = 0
                cleaned.append({"id": ident, "text": text, "at": at})
        self.entries = cleaned[: self.limit]

    def save(self) -> None:
        write_private_json(
            self.path,
            {"kind": "clipboard", "entries": self.entries},
        )

    def _new_id(self) -> str:
        return "c-" + secrets.token_hex(4)

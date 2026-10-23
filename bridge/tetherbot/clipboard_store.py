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
    CLIPBOARD_TEXT_MAX,
    DEFAULT_EXCLUDED_APPS,
    LOOKALIKE_SKIP,
    MASK_SECONDS,
    OFFER_RESULTS,
    clamp_clipboard_limit,
    clamp_lookalike_mode,
    classify_clipboard,
    excluded_apps,
)
from tetherbot.files import write_private_json
from tetherbot.todos import PALETTE_NAMES, tag_color

_ID = re.compile(r"^c-[0-9a-f]{8}$")
_TAG_MAX = 8
_TAG_LEN = 40


class ClipboardHistory:
    """Newest-first plain-text history with a cap."""

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        limit: int = CLIPBOARD_LIMIT_DEFAULT,
        excluded: object = DEFAULT_EXCLUDED_APPS,
        lookalike: str = LOOKALIKE_SKIP,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.path = path
        self.enabled = enabled is True
        self.limit = clamp_clipboard_limit(limit)
        self.excluded = excluded_apps(excluded)
        self.lookalike = clamp_lookalike_mode(lookalike)
        self._clock = clock or (lambda: int(time.time()))
        self.entries: list[dict[str, Any]] = []
        self.last_offer: dict[str, Any] | None = None
        self.load()

    def configure(
        self,
        *,
        enabled: bool,
        limit: int,
        excluded: object,
        lookalike: str = LOOKALIKE_SKIP,
    ) -> None:
        """Apply settings. A lower cap drops the oldest entries.

        Skip mode drops a hidden password immediately. Mask mode keeps
        one only until its deadline.
        """

        self.enabled = enabled is True
        self.limit = clamp_clipboard_limit(limit)
        self.excluded = excluded_apps(excluded)
        self.lookalike = clamp_lookalike_mode(lookalike)
        before = [dict(row) for row in self.entries]
        self.purge()
        if self.lookalike != "mask":
            self.entries = [row for row in self.entries if row.get("masked") is not True]
        self._trim()
        if self.entries != before:
            self.save()

    def offer(self, text: str, mimes: object, wm_class: object) -> str:
        """Store plain text, or return a skip reason. The text is not logged."""

        self.purge()
        result = classify_clipboard(
            text,
            mimes,
            wm_class,
            enabled=self.enabled,
            excluded=self.excluded,
            lookalike=self.lookalike,
        )
        self._remember(mimes, wm_class, result)
        if result not in {"stored", "stored-masked"} or not isinstance(text, str):
            self.save()
            return result
        self._store(text, masked=result == "stored-masked")
        return result

    def note(self, mimes: object, wm_class: object, result: object) -> None:
        """Record a decision that has no text. Unknown results are ignored."""

        if not isinstance(result, str) or result not in OFFER_RESULTS:
            return
        self._remember(mimes, wm_class, result)
        self.save()

    def list_entries(self, query: str = "") -> list[dict[str, Any]]:
        self.purge()
        needle = query.casefold().strip() if isinstance(query, str) else ""
        rows: list[dict[str, Any]] = []
        for row in self.entries:
            if needle and not _query_hit(row, needle):
                continue
            rows.append(_public_entry(row))
        return rows

    def set_pinned(self, entry_id: str, pinned: bool) -> bool:
        """Pin or unpin. Pinned rows stay at the top and out of the cap."""

        row = self._find(entry_id)
        if row is None or not isinstance(pinned, bool):
            return False
        if pinned:
            row["pinned"] = True
        else:
            row.pop("pinned", None)
        self._trim()
        self.save()
        return True

    def set_tags(self, entry_id: str, tags: object) -> bool:
        """Replace tags. Each kept tag has a name and a palette color."""

        row = self._find(entry_id)
        if row is None:
            return False
        cleaned = _clean_tags(tags)
        if cleaned:
            row["tags"] = cleaned
        else:
            row.pop("tags", None)
        self.save()
        return True

    def edit_text(self, entry_id: str, text: object) -> bool:
        """Replace the text. A hidden password is left unchanged."""

        row = self._find(entry_id)
        if row is None or row.get("masked") is True:
            return False
        if not isinstance(text, str) or "\x00" in text or not text.strip():
            return False
        if len(text.encode("utf-8")) > CLIPBOARD_TEXT_MAX:
            return False
        row["text"] = text
        self.save()
        return True

    def purge(self) -> bool:
        """Drop hidden entries whose 30 seconds are over. Text is not logged."""

        now = int(self._clock())
        kept: list[dict[str, Any]] = []
        removed = False
        for row in self.entries:
            until = row.get("until")
            if (
                row.get("masked") is True
                and isinstance(until, int)
                and not isinstance(until, bool)
                and until <= now
            ):
                removed = True
                continue
            kept.append(row)
        if removed:
            self.entries = kept
            self.save()
        return removed

    def mask_wait(self) -> int | None:
        """Seconds until the next hidden entry expires, or none."""

        now = int(self._clock())
        soon: int | None = None
        for row in self.entries:
            until = row.get("until")
            if (
                row.get("masked") is True
                and isinstance(until, int)
                and not isinstance(until, bool)
            ):
                if soon is None or until < soon:
                    soon = until
        if soon is None:
            return None
        return max(1, soon - now)

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
        """Remove unpinned entries. Pinned entries stay."""

        self.entries = [row for row in self.entries if row.get("pinned") is True]
        self._sort()
        self.save()
        return True

    def load(self) -> None:
        if not self.path.is_file():
            self.entries = []
            self.last_offer = None
            return
        try:
            os.chmod(self.path, 0o600)
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            self.entries = []
            self.last_offer = None
            return
        rows = payload.get("entries") if isinstance(payload, dict) else None
        raw_offer = payload.get("last_offer") if isinstance(payload, dict) else None
        self.last_offer = _clean_offer(raw_offer)
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
                item: dict[str, Any] = {"id": ident, "text": text, "at": at}
                if row.get("pinned") is True:
                    item["pinned"] = True
                tags = _clean_tags(row.get("tags"))
                if tags:
                    item["tags"] = tags
                if row.get("masked") is True:
                    until = row.get("until")
                    if isinstance(until, bool) or not isinstance(until, int):
                        continue
                    item["masked"] = True
                    item["until"] = until
                cleaned.append(item)
        self.entries = cleaned
        self._trim()
        self.purge()

    def save(self) -> None:
        payload: dict[str, Any] = {"kind": "clipboard", "entries": self.entries}
        if self.last_offer is not None:
            payload["last_offer"] = self.last_offer
        write_private_json(self.path, payload)

    def _store(self, text: str, *, masked: bool) -> None:
        now = int(self._clock())
        current = next((row for row in self.entries if row["text"] == text), None)
        entry: dict[str, Any] = {
            "id": current["id"] if current is not None else self._new_id(),
            "text": text,
            "at": now,
        }
        if current is not None and current.get("pinned") is True:
            entry["pinned"] = True
        if current is not None and current.get("tags"):
            entry["tags"] = current["tags"]
        if masked:
            entry["masked"] = True
            entry["until"] = now + MASK_SECONDS
        self.entries = [entry, *[row for row in self.entries if row["id"] != entry["id"]]]
        self._trim()
        self.save()

    def _find(self, entry_id: str) -> dict[str, Any] | None:
        if not isinstance(entry_id, str) or not _ID.fullmatch(entry_id):
            return None
        return next((row for row in self.entries if row["id"] == entry_id), None)

    def _sort(self) -> None:
        def stamp(row: dict[str, Any]) -> int:
            value = row.get("at")
            if isinstance(value, bool) or not isinstance(value, int):
                return 0
            return value

        pinned = [row for row in self.entries if row.get("pinned") is True]
        rest = [row for row in self.entries if row.get("pinned") is not True]
        pinned.sort(key=stamp, reverse=True)
        rest.sort(key=stamp, reverse=True)
        self.entries = pinned + rest

    def _trim(self) -> None:
        """Drop the oldest unpinned rows. Pinned rows stay."""

        self._sort()
        pinned = [row for row in self.entries if row.get("pinned") is True]
        rest = [row for row in self.entries if row.get("pinned") is not True]
        self.entries = pinned + rest[: self.limit]

    def _remember(self, mimes: object, wm_class: object, result: str) -> None:
        """Keep the decision. The copied text is not a field."""

        names = [mime for mime in _mimes(mimes) if mime and len(mime) <= 200 and "\n" not in mime]
        wm = wm_class if isinstance(wm_class, str) else ""
        if "\n" in wm or len(wm) > 128:
            wm = ""
        self.last_offer = {
            "at": int(self._clock()),
            "mimes": names[:32],
            "result": result,
            "wm_class": wm,
        }

    def _new_id(self) -> str:
        return "c-" + secrets.token_hex(4)


def _clean_offer(raw: object) -> dict[str, Any] | None:
    """A stored decision with no text field."""

    if not isinstance(raw, dict):
        return None
    result = raw.get("result")
    if not isinstance(result, str) or result not in OFFER_RESULTS:
        return None
    mimes = raw.get("mimes")
    names = []
    if isinstance(mimes, list):
        for mime in mimes:
            if isinstance(mime, str) and mime and len(mime) <= 200 and "\n" not in mime:
                names.append(mime)
    wm_class = raw.get("wm_class")
    if not isinstance(wm_class, str) or "\n" in wm_class or len(wm_class) > 128:
        wm_class = ""
    at = raw.get("at")
    if isinstance(at, bool) or not isinstance(at, int):
        at = 0
    return {"at": at, "mimes": names[:32], "result": result, "wm_class": wm_class}


def _public_entry(row: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": row["id"],
        "text": str(row["text"]),
        "at": row["at"],
        "pinned": row.get("pinned") is True,
        "tags": list(row.get("tags") or []),
    }
    if row.get("masked") is True:
        item["masked"] = True
    return item


def _query_hit(row: dict[str, Any], needle: str) -> bool:
    for tag in row.get("tags") or []:
        name = tag.get("name") if isinstance(tag, dict) else ""
        if isinstance(name, str) and needle in name.casefold():
            return True
    if row.get("masked") is True:
        return False
    return needle in str(row["text"]).casefold()


def _clean_tags(value: object) -> list[dict[str, str]]:
    if isinstance(value, str) or not isinstance(value, list):
        return []
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            name = _tag_name(item)
            color = ""
        elif isinstance(item, dict):
            name = _tag_name(item.get("name"))
            raw = item.get("color")
            color = raw if isinstance(raw, str) else ""
        else:
            continue
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        if color not in PALETTE_NAMES:
            color = tag_color(name)
        cleaned.append({"name": name, "color": color})
        if len(cleaned) >= _TAG_MAX:
            break
    return cleaned


def _tag_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = " ".join(value.split())
    if not name or len(name) > _TAG_LEN:
        return ""
    if any(ord(char) < 32 for char in name):
        return ""
    return name


def _mimes(values: object) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, str))

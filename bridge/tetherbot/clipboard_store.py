# SPDX-License-Identifier: GPL-2.0-or-later
"""Local clipboard history.

The file is mode 0600 under the bridge state directory. Image bytes live
beside it, under ``clipboard-images``, each file mode 0600. Entries are not
written to the feed, the queue, or a log.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import struct
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tetherbot.clipboard_policy import (
    CLIPBOARD_LIMIT_DEFAULT,
    CLIPBOARD_TEXT_MAX,
    DEFAULT_EXCLUDED_APPS,
    IMAGE_COUNT_MAX,
    IMAGE_MAX_BYTES,
    LOOKALIKE_SKIP,
    MASK_SECONDS,
    OFFER_RESULTS,
    canonical_image_mime,
    clamp_clipboard_limit,
    clamp_lookalike_mode,
    classify_clipboard,
    classify_image,
    dimensions_ok,
    excluded_apps,
    image_extension,
    image_label,
)
from tetherbot.files import ensure_private_dir, write_private_bytes, write_private_json
from tetherbot.todos import PALETTE_NAMES, tag_color

_ID = re.compile(r"^c-[0-9a-f]{8}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_NAME = re.compile(
    r"^c-[0-9a-f]{8}(?:\.(?:png|jpg|webp|bmp|gif|tiff|svg)|(?:\.thumb\.png))$"
)
_TAG_MAX = 8
_TAG_LEN = 40


class ClipboardHistory:
    """Newest-first history with a cap. Text and images share that cap."""

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        limit: int = CLIPBOARD_LIMIT_DEFAULT,
        excluded: object = DEFAULT_EXCLUDED_APPS,
        lookalike: str = LOOKALIKE_SKIP,
        images: bool = True,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.path = path
        self.image_dir = path.parent / "clipboard-images"
        self.enabled = enabled is True
        self.images = images is True
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
        images: bool = True,
    ) -> None:
        """Apply settings. A lower cap drops the oldest entries.

        Skip mode drops a hidden password immediately. Mask mode keeps
        one only until its deadline.
        """

        self.enabled = enabled is True
        self.images = images is True
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

    def offer_image(self, data: object, mimes: object, wm_class: object, mime: object) -> str:
        """Store one image, or return a skip reason.

        The bytes and the file path are not logged. A plain-text target
        is not stored here. A duplicate hash updates the existing row.
        """

        self.purge()
        blob = bytes(data) if isinstance(data, (bytes, bytearray, memoryview)) else None
        size = -1 if blob is None else len(blob)
        result = classify_image(
            mimes,
            wm_class,
            mime,
            size,
            enabled=self.enabled,
            images=self.images,
            excluded=self.excluded,
        )
        if result != "stored" or blob is None:
            self._remember(mimes, wm_class, result)
            self.save()
            return result
        chosen = canonical_image_mime(mime)
        inspected = None if chosen is None else _inspect_image(blob, chosen)
        if inspected is None or chosen is None:
            self._remember(mimes, wm_class, "skipped-image-bad")
            self.save()
            return "skipped-image-bad"
        _mime, width, height = inspected
        if not dimensions_ok(width, height):
            self._remember(mimes, wm_class, "skipped-image-large")
            self.save()
            return "skipped-image-large"
        decoded = _decode_image(blob, chosen, width, height)
        if decoded == "large":
            self._remember(mimes, wm_class, "skipped-image-large")
            self.save()
            return "skipped-image-large"
        if not isinstance(decoded, tuple):
            self._remember(mimes, wm_class, "skipped-image-bad")
            self.save()
            return "skipped-image-bad"
        width, height, thumb = decoded
        self._remember(mimes, wm_class, "stored")
        self._store_image(blob, chosen, width, height, thumb)
        return "stored"

    def read_image(self, entry_id: str) -> tuple[str, bytes] | None:
        """The original bytes for one image, or none. The path is not logged."""

        row = self._find(entry_id)
        if row is None or row.get("kind") != "image":
            return None
        mime = row.get("mime")
        if not isinstance(mime, str):
            return None
        path = self._file_for(row["id"], mime)
        try:
            blob = path.read_bytes()
        except OSError:
            return None
        if len(blob) > IMAGE_MAX_BYTES:
            return None
        return mime, blob

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
            rows.append(self._public_entry(row))
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
        if row is None or row.get("masked") is True:
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
        if row is None or row.get("masked") is True or row.get("kind") == "image":
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
        removed = [row for row in self.entries if row["id"] == entry_id]
        if not removed:
            return False
        self._drop_files(removed)
        self.entries = [row for row in self.entries if row["id"] != entry_id]
        self.save()
        return True

    def clear(self) -> bool:
        """Remove unpinned entries. Pinned entries stay. Image files go too."""

        removed = [row for row in self.entries if row.get("pinned") is not True]
        self._drop_files(removed)
        self.entries = [row for row in self.entries if row.get("pinned") is True]
        self._sort()
        self.save()
        return True

    def load(self) -> None:
        if self.image_dir.is_dir():
            ensure_private_dir(self.image_dir)
        if not self.path.is_file():
            self.entries = []
            self.last_offer = None
            self._sweep_orphans()
            return
        try:
            os.chmod(self.path, 0o600)
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            self.entries = []
            self.last_offer = None
            self._sweep_orphans()
            return
        rows = payload.get("entries") if isinstance(payload, dict) else None
        raw_offer = payload.get("last_offer") if isinstance(payload, dict) else None
        self.last_offer = _clean_offer(raw_offer)
        cleaned: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ident = row.get("id")
                at = row.get("at")
                if not isinstance(ident, str) or not _ID.fullmatch(ident):
                    continue
                if isinstance(at, bool) or not isinstance(at, int):
                    at = 0
                kind = row.get("kind")
                if kind == "image":
                    item = self._clean_image_row(row, ident, at)
                    if item is not None:
                        cleaned.append(item)
                    continue
                if kind not in (None, "text"):
                    continue
                text = row.get("text")
                if not isinstance(text, str):
                    continue
                item = {"id": ident, "text": text, "at": at}
                if row.get("pinned") is True:
                    item["pinned"] = True
                masked = row.get("masked") is True
                tags = [] if masked else _clean_tags(row.get("tags"))
                if tags:
                    item["tags"] = tags
                if masked:
                    until = row.get("until")
                    if isinstance(until, bool) or not isinstance(until, int):
                        continue
                    item["masked"] = True
                    item["until"] = until
                cleaned.append(item)
        self.entries = cleaned
        self._trim()
        self.purge()
        self._sweep_orphans()

    def save(self) -> None:
        payload: dict[str, Any] = {"kind": "clipboard", "entries": self.entries}
        if self.last_offer is not None:
            payload["last_offer"] = self.last_offer
        write_private_json(self.path, payload)

    def _store(self, text: str, *, masked: bool) -> None:
        now = int(self._clock())
        current = next(
            (
                row
                for row in self.entries
                if row.get("kind") != "image" and row.get("text") == text
            ),
            None,
        )
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

    def _store_image(
        self,
        data: bytes,
        mime: str,
        width: int | None,
        height: int | None,
        thumb: bytes | None,
    ) -> None:
        digest = hashlib.sha256(data).hexdigest()
        current = next(
            (
                row
                for row in self.entries
                if row.get("kind") == "image" and row.get("sha256") == digest
            ),
            None,
        )
        now = int(self._clock())
        ident = current["id"] if current is not None else self._new_id()
        kept_mime = mime
        if current is not None and isinstance(current.get("mime"), str):
            kept_mime = current["mime"]
        entry: dict[str, Any] = {
            "id": ident,
            "kind": "image",
            "mime": kept_mime,
            "size": len(data),
            "sha256": digest,
            "at": now,
        }
        if isinstance(width, int) and isinstance(height, int):
            entry["width"] = width
            entry["height"] = height
        if current is not None and current.get("pinned") is True:
            entry["pinned"] = True
        if current is not None and current.get("tags"):
            entry["tags"] = current["tags"]
        path = self._file_for(ident, kept_mime)
        thumb_path = self._thumb_for(ident)
        if current is None or not path.is_file():
            write_private_bytes(path, data)
            if thumb:
                write_private_bytes(thumb_path, thumb)
        elif thumb and not thumb_path.is_file():
            write_private_bytes(thumb_path, thumb)
        self.entries = [entry, *[row for row in self.entries if row["id"] != ident]]
        self._trim()
        self.save()

    def _clean_image_row(self, row: dict[str, Any], ident: str, at: int) -> dict[str, Any] | None:
        mime = canonical_image_mime(row.get("mime"))
        digest = row.get("sha256")
        if mime is None or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            return None
        path = self._file_for(ident, mime)
        if not path.is_file():
            return None
        try:
            os.chmod(path, 0o600)
            actual = path.stat().st_size
        except OSError:
            return None
        if actual <= 0 or actual > IMAGE_MAX_BYTES:
            self._unlink_in_dir(path)
            self._unlink_in_dir(self._thumb_for(ident))
            return None
        width = _optional_dim(row.get("width"))
        height = _optional_dim(row.get("height"))
        if (width is None) != (height is None) or not dimensions_ok(width, height):
            self._unlink_in_dir(path)
            self._unlink_in_dir(self._thumb_for(ident))
            return None
        item: dict[str, Any] = {
            "id": ident,
            "kind": "image",
            "mime": mime,
            "size": actual,
            "sha256": digest,
            "at": at,
        }
        if width is not None and height is not None:
            item["width"] = width
            item["height"] = height
        if row.get("pinned") is True:
            item["pinned"] = True
        tags = _clean_tags(row.get("tags"))
        if tags:
            item["tags"] = tags
        thumb = self._thumb_for(ident)
        if thumb.is_file():
            try:
                os.chmod(thumb, 0o600)
            except OSError:
                pass
        return item

    def _file_for(self, ident: str, mime: str) -> Path:
        ext = image_extension(mime)
        if ext is None or not _ID.fullmatch(ident):
            return self.image_dir / ".invalid"
        return self.image_dir / f"{ident}.{ext}"

    def _thumb_for(self, ident: str) -> Path:
        return self.image_dir / f"{ident}.thumb.png"

    def _drop_files(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if row.get("kind") != "image":
                continue
            ident = row.get("id")
            mime = row.get("mime")
            if not isinstance(ident, str) or not isinstance(mime, str):
                continue
            self._unlink_in_dir(self._file_for(ident, mime))
            self._unlink_in_dir(self._thumb_for(ident))

    def _unlink_in_dir(self, path: Path) -> None:
        try:
            directory = self.image_dir.resolve()
            parent = path.parent.resolve()
        except OSError:
            return
        if parent != directory:
            return
        name = path.name
        if not _IMAGE_NAME.fullmatch(name) and not (name.startswith(".") and name.endswith(".tmp")):
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return

    def _sweep_orphans(self) -> None:
        if not self.image_dir.is_dir():
            return
        keep: set[str] = set()
        for row in self.entries:
            if row.get("kind") != "image":
                continue
            ident = row.get("id")
            mime = row.get("mime")
            if not isinstance(ident, str) or not isinstance(mime, str):
                continue
            keep.add(self._file_for(ident, mime).name)
            keep.add(self._thumb_for(ident).name)
        try:
            children = list(self.image_dir.iterdir())
        except OSError:
            return
        for child in children:
            if child.name in keep:
                continue
            self._unlink_in_dir(child)

    def _public_entry(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("kind") == "image":
            mime = str(row.get("mime") or "")
            size = row.get("size")
            item: dict[str, Any] = {
                "id": row["id"],
                "kind": "image",
                "mime": mime,
                "size": size if isinstance(size, int) else 0,
                "at": row["at"],
                "pinned": row.get("pinned") is True,
                "tags": list(row.get("tags") or []),
                "text": "",
                "path": str(self._file_for(row["id"], mime)),
            }
            width = row.get("width")
            height = row.get("height")
            if isinstance(width, int) and isinstance(height, int):
                item["width"] = width
                item["height"] = height
            thumb = self._thumb_for(row["id"])
            if thumb.is_file():
                item["thumb"] = str(thumb)
            return item
        item = {
            "id": row["id"],
            "text": str(row.get("text") or ""),
            "at": row["at"],
            "pinned": row.get("pinned") is True,
            "tags": list(row.get("tags") or []),
        }
        if row.get("masked") is True:
            item["masked"] = True
        return item

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
        """Drop the oldest unpinned rows. Pinned rows stay.

        Unpinned images also stop at the image cap. Dropped image files
        are unlinked.
        """

        self._sort()
        pinned = [row for row in self.entries if row.get("pinned") is True]
        rest = [row for row in self.entries if row.get("pinned") is not True]
        images = [row for row in rest if row.get("kind") == "image"]
        dropped = images[IMAGE_COUNT_MAX:]
        drop_ids = {row["id"] for row in dropped}
        rest = [row for row in rest if row["id"] not in drop_ids]
        if len(rest) > self.limit:
            dropped.extend(rest[self.limit :])
            rest = rest[: self.limit]
        self._drop_files(dropped)
        self.entries = pinned + rest

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


def _query_hit(row: dict[str, Any], needle: str) -> bool:
    for tag in row.get("tags") or []:
        name = tag.get("name") if isinstance(tag, dict) else ""
        if isinstance(name, str) and needle in name.casefold():
            return True
    if row.get("kind") == "image":
        label = image_label(row.get("mime"), row.get("size")).casefold()
        mime = str(row.get("mime") or "").casefold()
        return needle in label or needle in mime
    if row.get("masked") is True:
        return False
    return needle in str(row.get("text") or "").casefold()


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


def _optional_dim(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _inspect_image(data: bytes, mime: str) -> tuple[str, int | None, int | None] | None:
    """Return the type and pixel size when the bytes match ``mime``."""

    if mime == "image/png":
        size = _png_size(data)
        return None if size is None else (mime, size[0], size[1])
    if mime == "image/gif":
        size = _gif_size(data)
        return None if size is None else (mime, size[0], size[1])
    if mime == "image/bmp":
        size = _bmp_size(data)
        return None if size is None else (mime, size[0], size[1])
    if mime == "image/jpeg":
        if not data.startswith(b"\xff\xd8"):
            return None
        size = _jpeg_size(data)
        return (mime, None, None) if size is None else (mime, size[0], size[1])
    if mime == "image/webp":
        if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
            return None
        size = _webp_size(data)
        return (mime, None, None) if size is None else (mime, size[0], size[1])
    if mime == "image/tiff":
        if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
            return (mime, None, None)
        return None
    if mime == "image/svg+xml":
        return (mime, None, None) if _looks_like_svg(data) else None
    return None


def _decode_image(
    data: bytes,
    mime: str,
    width: int | None,
    height: int | None,
) -> tuple[int | None, int | None, bytes | None] | str:
    """Pixel size and a small PNG, or ``large`` or ``bad``. Nothing is logged."""

    if not dimensions_ok(width, height):
        return "large"
    decoded = _pixbuf_decode(data, mime)
    if decoded == "unavailable":
        if mime == "image/png" and width and height and _png_idat_ok(data):
            return width, height, None
        return "bad"
    return decoded


def _pixbuf_decode(data: bytes, mime: str) -> tuple[int | None, int | None, bytes | None] | str:
    try:
        import gi

        try:
            gi.require_version("GdkPixbuf", "2.0")
        except ValueError:
            pass
        from gi.repository import GdkPixbuf
    except Exception:
        return "unavailable"
    too_big = False

    def _prepared(loader: object, side_w: int, side_h: int, *_rest: object) -> None:
        nonlocal too_big
        if dimensions_ok(side_w, side_h):
            return
        too_big = True
        try:
            loader.set_size(1, 1)  # type: ignore[attr-defined]
        except Exception:
            return

    try:
        loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
    except Exception:
        try:
            loader = GdkPixbuf.PixbufLoader()
        except Exception:
            return "unavailable"
    try:
        loader.connect("size-prepared", _prepared)
        loader.write(data)
        loader.close()
    except Exception:
        try:
            loader.close()
        except Exception:
            pass
        return "large" if too_big else "bad"
    if too_big:
        return "large"
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        return "bad"
    side_w = int(pixbuf.get_width())
    side_h = int(pixbuf.get_height())
    if not dimensions_ok(side_w, side_h):
        return "large"
    return side_w, side_h, _thumb_png(pixbuf)


def _thumb_png(pixbuf: object) -> bytes | None:
    try:
        from gi.repository import GdkPixbuf
    except Exception:
        return None
    side_w = int(pixbuf.get_width())  # type: ignore[attr-defined]
    side_h = int(pixbuf.get_height())  # type: ignore[attr-defined]
    if side_w <= 0 or side_h <= 0:
        return None
    scale = min(96 / side_w, 96 / side_h, 1)
    thumb_w = max(1, int(side_w * scale))
    thumb_h = max(1, int(side_h * scale))
    scaled = pixbuf.scale_simple(  # type: ignore[attr-defined]
        thumb_w,
        thumb_h,
        GdkPixbuf.InterpType.BILINEAR,
    )
    if scaled is None:
        return None
    try:
        ok, payload = scaled.save_to_bufferv("png", [], [])
    except Exception:
        return None
    if not ok:
        return None
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    getter = getattr(payload, "get_data", None)
    if callable(getter):
        try:
            return bytes(getter())
        except Exception:
            return None
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


def _png_idat_ok(data: bytes) -> bool:
    if _png_size(data) is None:
        return False
    offset = 8
    payload = bytearray()
    ended = False
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        tag = data[offset + 4 : offset + 8]
        offset += 8
        if offset + length + 4 > len(data):
            return False
        chunk = data[offset : offset + length]
        offset += length + 4
        if tag == b"IDAT":
            payload.extend(chunk)
        elif tag == b"IEND":
            ended = True
            break
    if not ended or not payload:
        return False
    try:
        zlib.decompress(bytes(payload))
    except zlib.error:
        return False
    return True


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or not data.startswith((b"GIF87a", b"GIF89a")):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    if width <= 0 or height <= 0:
        return None
    return width, height


def _bmp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 26 or not data.startswith(b"BM"):
        return None
    width, height = struct.unpack("<ii", data[18:26])
    height = abs(height)
    if width <= 0 or height <= 0:
        return None
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index + 3 < len(data):
        if data[index] != 0xFF:
            return None
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 1 >= len(data):
            return None
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            return None
        if marker in sof and length >= 7:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            if width > 0 and height > 0:
                return width, height
            return None
        index += length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 16:
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        if width > 0 and height > 0:
            return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        start = data.find(b"\x9d\x01\x2a")
        if start >= 0 and start + 7 <= len(data):
            width = int.from_bytes(data[start + 3 : start + 5], "little") & 0x3FFF
            height = int.from_bytes(data[start + 5 : start + 7], "little") & 0x3FFF
            if width > 0 and height > 0:
                return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        b0, b1, b2, b3 = data[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        if width > 0 and height > 0:
            return width, height
    return None


def _looks_like_svg(data: bytes) -> bool:
    """True for an SVG document. The bytes are not parsed as markup."""

    if not data or b"\x00" in data[:256]:
        return False
    head = data[:4096].lstrip().lower()
    if not head.startswith((b"<svg", b"<?xml", b"<")):
        return False
    return b"<svg" in head

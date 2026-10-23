# SPDX-License-Identifier: GPL-2.0-or-later
"""Decide whether a clipboard offer may be stored.

Plain text is the default. A sensitive target, an excluded app, or a
password lookalike is skipped. Chrome and Chromium on Linux offer ordinary
text targets for a password copy. They do not set ``x-kde-passwordManagerHint``
or a concealed type. The lookalike rule is what skips that copy.

An image is a separate offer. A real plain-text target wins over an image.
``text/html`` alone does not. Images are not password lookalikes. A
sensitive hint or an excluded app still skips them.

This module does not read the clipboard, open a socket, or write a file.
"""

from __future__ import annotations

import re

CLIPBOARD_LIMIT_DEFAULT = 50
CLIPBOARD_LIMIT_MIN = 1
CLIPBOARD_LIMIT_MAX = 500
CLIPBOARD_TEXT_MAX = 1_000_000
CLIPBOARD_APP_MAX = 64
IMAGE_MAX_BYTES = 10 * 1024 * 1024
IMAGE_COUNT_MAX = 20
IMAGE_MAX_EDGE = 8192
IMAGE_MAX_PIXELS = 16_777_216
IMAGE_MIME_ORDER = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/gif",
    "image/tiff",
    "image/svg+xml",
)
LOOKALIKE_SKIP = "skip"
LOOKALIKE_MASK = "mask"
LOOKALIKE_MODES = (LOOKALIKE_SKIP, LOOKALIKE_MASK)
LOOKALIKE_MIN = 8
LOOKALIKE_MAX = 128
MASK_SECONDS = 30
OFFER_RESULTS = (
    "stored",
    "stored-masked",
    "skipped-sensitive",
    "skipped-app",
    "skipped-disabled",
    "skipped-empty",
    "skipped-binary",
    "skipped-huge",
    "skipped-lookalike",
    "skipped-images-off",
    "skipped-image-large",
    "skipped-image-bad",
)
OFFER_REASONS = {
    "stored": "kept",
    "stored-masked": "hidden for 30 seconds",
    "skipped-sensitive": "sensitive clipboard type",
    "skipped-app": "excluded app",
    "skipped-disabled": "clipboard history is off",
    "skipped-empty": "empty",
    "skipped-binary": "not plain text",
    "skipped-huge": "too large",
    "skipped-lookalike": "password lookalike",
    "skipped-images-off": "images-off",
    "skipped-image-large": "image-too-large",
    "skipped-image-bad": "image-unreadable",
}
_IMAGE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/tiff": "tiff",
    "image/svg+xml": "svg",
}
_IMAGE_NAMES = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/webp": "WEBP",
    "image/bmp": "BMP",
    "image/gif": "GIF",
    "image/tiff": "TIFF",
    "image/svg+xml": "SVG",
}

DEFAULT_EXCLUDED_APPS: tuple[str, ...] = (
    "1password",
    "bitwarden",
    "keepassxc",
    "keepass",
    "org.keepassxc.KeePassXC",
    "org.gnome.World.Secrets",
    "gnome-keyring",
    "seahorse",
    "kwalletmanager",
    "kwallet",
    "proton-pass",
    "protonpass",
    "lastpass",
    "dashlane",
    "enpass",
    "gopass",
)

_APP = re.compile(r"^[A-Za-z0-9._-]{2,128}$")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FILENAME = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z]{1,8}$")
_TEXT_MIMES = frozenset(
    {
        "text/plain",
        "utf8_string",
        "string",
        "text",
        "compound_text",
        "text/unicode",
    }
)


def clamp_clipboard_limit(value: object) -> int:
    """Keep a history cap inside 1 to 500. A non-positive value is 50."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return CLIPBOARD_LIMIT_DEFAULT
    return min(CLIPBOARD_LIMIT_MAX, max(CLIPBOARD_LIMIT_MIN, value))


def excluded_apps(values: object) -> tuple[str, ...]:
    """Window-class ids. Empty input stays empty. Duplicates are dropped."""

    if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    seen: list[str] = []
    folded: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not _APP.fullmatch(value.strip()):
            continue
        name = value.strip()
        key = name.casefold()
        if key in folded:
            continue
        folded.add(key)
        seen.append(name)
        if len(seen) >= CLIPBOARD_APP_MAX:
            break
    return tuple(seen)


def list_preview(text: object, limit: int = 180) -> str:
    """One short line for a list. The full text stays available for preview."""

    if not isinstance(text, str):
        return ""
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    if limit <= 1:
        return "…"
    return line[: limit - 1] + "…"


def clamp_lookalike_mode(value: object) -> str:
    """``skip`` or ``mask``. Anything else is ``skip``."""

    if isinstance(value, str):
        mode = value.strip().casefold()
        if mode in LOOKALIKE_MODES:
            return mode
    return LOOKALIKE_SKIP


def looks_like_password(text: object) -> bool:
    """True for one short token that mixes character classes.

    A URL, a path, a number, an email address, a UUID, and a simple
    file name are not lookalikes. The text is not stored here.
    """

    body = _single_line(text)
    if body is None:
        return False
    if not LOOKALIKE_MIN <= len(body) <= LOOKALIKE_MAX:
        return False
    folded = body.casefold()
    if "://" in body or folded.startswith("www."):
        return False
    if "/" in body or "\\" in body or body.startswith("~"):
        return False
    if body.isdigit():
        return False
    if _UUID.fullmatch(body) or _EMAIL.fullmatch(body) or _FILENAME.fullmatch(body):
        return False
    lower = upper = digit = symbol = False
    for char in body:
        if "a" <= char <= "z":
            lower = True
        elif "A" <= char <= "Z":
            upper = True
        elif "0" <= char <= "9":
            digit = True
        else:
            symbol = True
    return sum((lower, upper, digit, symbol)) >= 3


def classify_clipboard(
    text: str | None,
    mimes: object,
    wm_class: object,
    *,
    enabled: bool,
    excluded: object,
    lookalike: str = LOOKALIKE_SKIP,
) -> str:
    """``stored`` when the offer may be kept. Otherwise a skip reason.

    ``text`` is ``None`` when the caller has not read the clipboard yet.
    Sensitive targets and excluded apps are decided before that read.
    ``stored-masked`` means the text may be kept hidden for 30 seconds.
    """

    if enabled is not True:
        return "skipped-disabled"
    types = _mimes(mimes)
    if any(_sensitive(mime) for mime in types):
        return "skipped-sensitive"
    if _app_excluded(wm_class, excluded):
        return "skipped-app"
    if types and not any(_text_mime(mime) for mime in types):
        return "skipped-binary"
    if text is None:
        return "needs-text"
    if not isinstance(text, str) or "\x00" in text:
        return "skipped-binary"
    if not text.strip():
        return "skipped-empty"
    if len(text.encode("utf-8")) > CLIPBOARD_TEXT_MAX:
        return "skipped-huge"
    if looks_like_password(text):
        if clamp_lookalike_mode(lookalike) == LOOKALIKE_MASK:
            return "stored-masked"
        return "skipped-lookalike"
    return "stored"


def format_clipboard_debug(payload: object) -> str:
    """MIME types and the skip reason. The copied text is never included."""

    offer = payload.get("last_offer") if isinstance(payload, dict) else None
    if not isinstance(offer, dict):
        return "result: none\nreason: no clipboard offer has been recorded\nmimes:\nwm_class:\n"
    result = offer.get("result")
    if not isinstance(result, str) or result not in OFFER_RESULTS:
        result = "none"
    reason = OFFER_REASONS.get(result, "no clipboard offer has been recorded")
    mimes = offer.get("mimes")
    names: list[str] = []
    if isinstance(mimes, list):
        for mime in mimes:
            if isinstance(mime, str) and mime and len(mime) <= 200 and "\n" not in mime:
                names.append(mime)
    wm_class = offer.get("wm_class")
    if not isinstance(wm_class, str) or "\n" in wm_class or len(wm_class) > 128:
        wm_class = ""
    return (
        f"result: {result}\n"
        f"reason: {reason}\n"
        f"mimes: {', '.join(names)}\n"
        f"wm_class: {wm_class}\n"
    )


def _mimes(values: object) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def _sensitive(mime: str) -> bool:
    """True when a target marks the copy private.

    Firefox and KeePassXC set ``x-kde-passwordManagerHint``. Some clients
    set a concealed or confidential type. Chrome on Linux does not, as of
    the current clipboard constants: a password copy is plain text.
    """

    folded = mime.casefold()
    return (
        "passwordmanagerhint" in folded
        or "concealed" in folded
        or "confidential" in folded
        or "sensitive" in folded
    )


def _single_line(text: object) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    body = text
    if body.endswith("\r\n"):
        body = body[:-2]
    elif body.endswith(("\n", "\r")):
        body = body[:-1]
    if not body or any(char.isspace() for char in body):
        return None
    return body


def _text_mime(mime: str) -> bool:
    folded = mime.casefold().strip()
    if folded in _TEXT_MIMES:
        return True
    return folded.split(";", 1)[0].strip() in _TEXT_MIMES


def canonical_image_mime(mime: object) -> str | None:
    """An allowed image type, or none. ``image/jpg`` is JPEG."""

    if not isinstance(mime, str):
        return None
    folded = mime.casefold().split(";", 1)[0].strip()
    if folded == "image/jpg":
        folded = "image/jpeg"
    if folded in _IMAGE_EXT:
        return folded
    return None


def image_extension(mime: object) -> str | None:
    """The file suffix for an allowed image type."""

    canonical = canonical_image_mime(mime)
    if canonical is None:
        return None
    return _IMAGE_EXT[canonical]


def pick_image_mime(mimes: object) -> str | None:
    """The image type to keep, or none when plain text wins.

    ``image/png`` wins over the other image types. A plain-text target,
    including ``UTF8_STRING``, keeps the text. ``text/html`` does not.
    """

    types = _mimes(mimes)
    if any(_text_mime(mime) for mime in types):
        return None
    found = [canonical for mime in types if (canonical := canonical_image_mime(mime))]
    if "image/png" in found:
        return "image/png"
    for mime in IMAGE_MIME_ORDER:
        if mime in found:
            return mime
    return None


def dimensions_ok(width: object, height: object) -> bool:
    """True when both sides are unknown, or both are inside the pixel cap."""

    if width is None and height is None:
        return True
    if isinstance(width, bool) or isinstance(height, bool):
        return False
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    if width <= 0 or height <= 0:
        return False
    if width > IMAGE_MAX_EDGE or height > IMAGE_MAX_EDGE:
        return False
    return width * height <= IMAGE_MAX_PIXELS


def image_label(mime: object, size: object) -> str:
    """One line such as ``Image · PNG · 1.2 MB``. The bytes are not included."""

    canonical = canonical_image_mime(mime)
    name = _IMAGE_NAMES.get(canonical or "", "Image")
    return f"Image · {name} · {_format_size(size)}"


def classify_image(
    mimes: object,
    wm_class: object,
    mime: object,
    size: object,
    *,
    enabled: bool,
    images: bool,
    excluded: object,
) -> str:
    """``stored`` when an image offer may be kept. Otherwise a skip reason.

    Sensitive targets and excluded apps are decided before the size cap.
    A plain-text target means the text offer wins, so this offer is not
    an image. The bytes are not read here.
    """

    if enabled is not True:
        return "skipped-disabled"
    if images is not True:
        return "skipped-images-off"
    types = _mimes(mimes)
    chosen = canonical_image_mime(mime)
    checked = types if chosen is None else (*types, chosen)
    if any(_sensitive(item) for item in checked):
        return "skipped-sensitive"
    if _app_excluded(wm_class, excluded):
        return "skipped-app"
    if any(_text_mime(item) for item in types):
        return "skipped-binary"
    if chosen is None:
        return "skipped-binary"
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return "skipped-image-bad"
    if size == 0:
        return "skipped-empty"
    if size > IMAGE_MAX_BYTES:
        return "skipped-image-large"
    return "stored"


def _format_size(size: object) -> str:
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return "0 B"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _app_excluded(wm_class: object, excluded: object) -> bool:
    if not isinstance(wm_class, str):
        return False
    folded = wm_class.casefold().strip()
    if not folded:
        return False
    for name in excluded_apps(excluded):
        ident = name.casefold()
        if folded == ident or ident in folded:
            return True
    return False

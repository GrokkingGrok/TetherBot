# SPDX-License-Identifier: GPL-2.0-or-later
"""Decide whether a clipboard offer may be stored.

Plain text only. A sensitive target, an excluded app, or a password
lookalike is skipped. Chrome and Chromium on Linux offer ordinary text
targets for a password copy. They do not set ``x-kde-passwordManagerHint``
or a concealed type. The lookalike rule is what skips that copy.

This module does not read the clipboard, open a socket, or write a file.
"""

from __future__ import annotations

import re

CLIPBOARD_LIMIT_DEFAULT = 50
CLIPBOARD_LIMIT_MIN = 1
CLIPBOARD_LIMIT_MAX = 500
CLIPBOARD_TEXT_MAX = 1_000_000
CLIPBOARD_APP_MAX = 64
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

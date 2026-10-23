# SPDX-License-Identifier: GPL-2.0-or-later
"""Decide whether a clipboard offer may be stored.

Plain text only. A sensitive target or an excluded app is skipped.
This module does not read the clipboard, open a socket, or write a file.
"""

from __future__ import annotations

import re

CLIPBOARD_LIMIT_DEFAULT = 50
CLIPBOARD_LIMIT_MIN = 1
CLIPBOARD_LIMIT_MAX = 500
CLIPBOARD_TEXT_MAX = 1_000_000
CLIPBOARD_APP_MAX = 64

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


def classify_clipboard(
    text: str | None,
    mimes: object,
    wm_class: object,
    *,
    enabled: bool,
    excluded: object,
) -> str:
    """``stored`` when the offer may be kept. Otherwise a skip reason.

    ``text`` is ``None`` when the caller has not read the clipboard yet.
    Sensitive targets and excluded apps are decided before that read.
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
    return "stored"


def _mimes(values: object) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def _sensitive(mime: str) -> bool:
    folded = mime.casefold()
    return "passwordmanagerhint" in folded or "concealed" in folded


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

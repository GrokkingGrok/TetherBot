# SPDX-License-Identifier: GPL-2.0-or-later
"""Short sentences for bridge errors shown in the window and the menu.

The raw GDBus string stays off the screen. A refusal that mentions a
secret becomes one fixed sentence. The refused text is never copied
into that sentence or into a log.
"""

from __future__ import annotations

import re

SECRET_NOTE_MESSAGE = "This note looks like a secret, so it wasn't sent."
BRIDGE_SILENT = "The bridge did not answer."

_DBUS_PREFIX = re.compile(r"^(?:GDBus\.Error:[A-Za-z0-9._]+:\s*)+")
_QUARK_PREFIX = re.compile(
    r"^(?:g-dbus-error-quark|g-io-error-quark):\s*",
    re.IGNORECASE,
)
_TRAILING_CODE = re.compile(r"\s+\(\d+\)\s*$")
_NO_ANSWER = ("noreply", "serviceunknown", "disconnected", "name has no owner")


def friendly_bridge_message(raw: object, fallback: str = "That could not be done.") -> str:
    """One readable sentence. A secret refusal is always the same sentence."""

    text = "" if raw is None else str(raw)
    if "looks like a secret" in text.casefold():
        return SECRET_NOTE_MESSAGE
    cleaned = text.strip()
    progressed = True
    while progressed and cleaned:
        progressed = False
        stripped = _DBUS_PREFIX.sub("", cleaned, count=1).strip()
        if stripped != cleaned:
            cleaned = stripped
            progressed = True
            continue
        stripped = _QUARK_PREFIX.sub("", cleaned, count=1).strip()
        if stripped != cleaned:
            cleaned = stripped
            progressed = True
    cleaned = _TRAILING_CODE.sub("", cleaned).strip()
    folded_raw = text.casefold()
    if any(marker in folded_raw for marker in _NO_ANSWER):
        return BRIDGE_SILENT
    folded = cleaned.casefold()
    if (
        not cleaned
        or "\n" in cleaned
        or "\r" in cleaned
        or len(cleaned) > 160
        or "gdbus" in folded
        or "org.freedesktop" in folded
        or "error-quark" in folded
    ):
        return fallback
    return cleaned


def clip_send_message(raw: object) -> str:
    """Clipboard send text. The secret sentence is shown on its own."""

    reason = friendly_bridge_message(raw, fallback="Could not send")
    if reason == SECRET_NOTE_MESSAGE or reason.startswith("Not sent"):
        return reason
    return f"Not sent: {reason}"

# SPDX-License-Identifier: GPL-2.0-or-later
"""Bridge errors become one short sentence, with no refused text in it."""

from tetherbot.bridge_errors import (
    BRIDGE_SILENT,
    SECRET_NOTE_MESSAGE,
    clip_send_message,
    friendly_bridge_message,
)
from tetherbot.model import looks_like_secret

_GDBus_SECRET = (
    "GDBus.Error:io.github.grokkinggrok.TetherBot1.Error.InvalidArgs: "
    "refusing to queue an action that looks like a secret"
)
_FAKE_PREFIX = "ghp_notarealtoken"


def test_a_secret_refusal_is_one_sentence_and_drops_the_refused_text():
    assert looks_like_secret(_FAKE_PREFIX)
    raw = f"{_GDBus_SECRET} {_FAKE_PREFIX}"
    message = friendly_bridge_message(raw)
    assert message == SECRET_NOTE_MESSAGE
    assert "GDBus" not in message
    assert "InvalidArgs" not in message
    assert _FAKE_PREFIX not in message
    assert _FAKE_PREFIX.casefold() not in message.casefold()
    assert friendly_bridge_message(_GDBus_SECRET.upper()) == SECRET_NOTE_MESSAGE


def test_other_bridge_errors_lose_the_dbus_prefix():
    assert friendly_bridge_message("No webhook set up") == "No webhook set up"
    assert friendly_bridge_message("could not send") == "could not send"
    quark = "g-dbus-error-quark: Wait a few seconds (36)"
    assert friendly_bridge_message(quark) == "Wait a few seconds"
    timeout = "g-io-error-quark: Timeout was reached (24)"
    assert friendly_bridge_message(timeout) == "Timeout was reached"
    nested = (
        "g-dbus-error-quark: GDBus.Error:org.freedesktop.DBus.Error.Failed: "
        "item not found (36)"
    )
    assert friendly_bridge_message(nested) == "item not found"


def test_a_missing_bridge_and_a_dump_stay_generic():
    noreply = (
        "GDBus.Error:org.freedesktop.DBus.Error.NoReply: "
        "Message recipient disconnected from message bus without replying"
    )
    assert friendly_bridge_message(noreply) == BRIDGE_SILENT
    unknown = (
        "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: "
        "The name has no owner"
    )
    assert friendly_bridge_message(unknown) == BRIDGE_SILENT
    assert friendly_bridge_message("") == "That could not be done."
    assert friendly_bridge_message(None) == "That could not be done."
    assert friendly_bridge_message("line one\nline two") == "That could not be done."
    assert friendly_bridge_message("x" * 161) == "That could not be done."
    assert (
        friendly_bridge_message("GDBus.Error:still.here", fallback="Could not save the timer")
        == "Could not save the timer"
    )


def test_clipboard_send_shows_the_secret_sentence_without_a_prefix():
    assert clip_send_message(_GDBus_SECRET) == SECRET_NOTE_MESSAGE
    assert clip_send_message("No webhook set up") == "Not sent: No webhook set up"
    assert clip_send_message("Not sent: already") == "Not sent: already"
    assert clip_send_message("") == "Not sent: Could not send"
    assert _FAKE_PREFIX not in clip_send_message(f"{_GDBus_SECRET} {_FAKE_PREFIX}")

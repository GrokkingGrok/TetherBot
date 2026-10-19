# SPDX-License-Identifier: GPL-2.0-or-later
"""Ask the single-instance TetherBot window to open.

The bridge does not import GTK. Activation goes through the session bus
name ``io.github.grokkinggrok.TetherBot``, which the window owns.
The request is asynchronous: a cold start talks back to the bridge, so
this call must return before that conversation begins.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

APP_ID = "io.github.grokkinggrok.TetherBot"
APP_PATH = "/io/github/grokkinggrok/TetherBot"

Launcher = Callable[[str], bool]
_LOG = logging.getLogger("tetherbot")


def launch_window(item_key: str) -> bool:
    """Request ``select-item``. True means the request was sent.

    False means the session bus could not take the request. The window
    may still be starting when this returns.
    """

    if not isinstance(item_key, str):
        return False
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        parameters = GLib.Variant(
            "(sava{sv})",
            ("select-item", [GLib.Variant("s", item_key)], {}),
        )
        bus.call(
            APP_ID,
            APP_PATH,
            "org.freedesktop.Application",
            "ActivateAction",
            parameters,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            _on_activate,
        )
    except Exception:
        return False
    return True


def _on_activate(bus: object, result: object) -> None:
    try:
        finish = getattr(bus, "call_finish")
        finish(result)
    except Exception:
        _LOG.info("window did not open")

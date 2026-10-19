# SPDX-License-Identifier: GPL-2.0-or-later
"""Ask the single-instance TetherBot window to open.

The bridge does not import GTK. Activation goes through the session bus
name ``io.github.grokkinggrok.TetherBot``, which the window owns.
"""

from __future__ import annotations

from collections.abc import Callable

APP_ID = "io.github.grokkinggrok.TetherBot"
APP_PATH = "/io/github/grokkinggrok/TetherBot"

Launcher = Callable[[str], bool]


def launch_window(item_key: str) -> bool:
    """Activate ``select-item``. False means the window did not start."""

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
        bus.call_sync(
            APP_ID,
            APP_PATH,
            "org.freedesktop.Application",
            "ActivateAction",
            parameters,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
    except Exception:
        return False
    return True

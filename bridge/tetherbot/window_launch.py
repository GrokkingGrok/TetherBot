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
    may still be starting when this returns. A dead window name is started
    once and the action is sent again. That failure is not a dead bridge.
    """

    if not isinstance(item_key, str):
        return False
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        return False
    return _activate_action(bus, item_key, retried=False)


def _activate_action(bus: object, item_key: str, *, retried: bool) -> bool:
    try:
        import gi

        gi.require_version("GLib", "2.0")
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        _LOG.info("window did not open")
        return False
    parameters = GLib.Variant(
        "(sava{sv})",
        ("select-item", [GLib.Variant("s", item_key)], {}),
    )

    def _done(source: object, result: object, retried: bool = retried) -> None:
        _on_activate(source, result, item_key=item_key, retried=retried)

    try:
        call = getattr(bus, "call")
        call(
            APP_ID,
            APP_PATH,
            "org.freedesktop.Application",
            "ActivateAction",
            parameters,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            _done,
        )
    except Exception:
        if retried:
            _LOG.info("window did not open")
            return False
        return _start_window(bus, item_key)
    return True


def _on_activate(bus: object, result: object, *, item_key: str = "", retried: bool = True) -> None:
    try:
        finish = getattr(bus, "call_finish")
        finish(result)
    except Exception:
        if retried or not item_key:
            _LOG.info("window did not open")
            return
        _start_window(bus, item_key)


def _start_window(bus: object, item_key: str) -> bool:
    """Start the window name once, then send ``select-item`` again."""

    try:
        import gi

        gi.require_version("GLib", "2.0")
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError):
        _LOG.info("window did not open")
        return False

    def _started(source: object, result: object) -> None:
        try:
            finish = getattr(source, "call_finish")
            finish(result)
        except Exception:
            _LOG.info("window did not open")
            return
        _activate_action(source, item_key, retried=True)

    try:
        call = getattr(bus, "call")
        call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "StartServiceByName",
            GLib.Variant("(su)", (APP_ID, 0)),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            _started,
        )
    except Exception:
        _LOG.info("window did not open")
        return False
    return True

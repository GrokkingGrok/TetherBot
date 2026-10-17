# SPDX-License-Identifier: GPL-2.0-or-later
"""D-Bus session API.

``data/io.github.grokkinggrok.TetherBot1.xml`` is the interface source of truth.
``SessionExport`` owns the bus name and forwards calls to ``BridgeApi``.
Importing this module does not import PyGObject. Secrets never go on this bus.

The bus name, object path, and interface are frozen. Leave them unchanged
after release. A breaking change bumps the interface to TetherBot2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BUS_NAME = "io.github.grokkinggrok.TetherBot1"
OBJECT_PATH = "/io/github/grokkinggrok/TetherBot1"
INTERFACE = "io.github.grokkinggrok.TetherBot1"

STATES = (
    "unconfigured",
    "ok",
    "degraded",
    "offline",
    "failed_closed",
    "paused",
)


def interface_xml_path() -> Path:
    """Return the introspection XML path in a source checkout."""

    return Path(__file__).resolve().parents[2] / "data" / "io.github.grokkinggrok.TetherBot1.xml"


def interface_xml() -> str:
    return interface_xml_path().read_text(encoding="utf-8")


class BusOwnershipError(RuntimeError):
    """The session name could not be claimed."""


class SessionExport:
    """Export ``BridgeApi`` on the session bus. Constructing it does not connect."""

    def __init__(self, api: Any) -> None:
        self._api = api
        self._connection: Any = None
        self._registration = 0
        self._owned = False
        self._gio: Any = None
        self._glib: Any = None

    def acquire(self) -> None:
        """Register the object and request the well-known name."""

        try:
            import gi

            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as exc:
            raise ImportError("PyGObject Gio is not available") from exc
        self._gio = Gio
        self._glib = GLib
        self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(interface_xml())
        self._registration = self._connection.register_object(
            OBJECT_PATH,
            node.interfaces[0],
            self._method_call,
            self._get_property,
            self._set_property,
        )
        reply = self._connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            GLib.Variant("(su)", (BUS_NAME, 4)),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        code = int(reply.unpack()[0])
        if code not in (1, 4):
            self.release()
            raise BusOwnershipError("bus name is already owned")
        self._owned = True
        self._api.subscribe(self._on_api_signal)

    def release(self) -> None:
        """Drop the well-known name and the object registration."""

        connection = self._connection
        if connection is None:
            return
        if self._owned:
            self._owned = False
            try:
                connection.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "ReleaseName",
                    self._glib.Variant("(s)", (BUS_NAME,)),
                    self._glib.VariantType("(u)"),
                    self._gio.DBusCallFlags.NONE,
                    5000,
                    None,
                )
            except Exception:
                pass
        if self._registration:
            registration = self._registration
            self._registration = 0
            try:
                connection.unregister_object(registration)
            except Exception:
                pass
        self._connection = None

    def _method_call(
        self,
        _connection: Any,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters: Any,
        invocation: Any,
    ) -> None:
        from tetherbot.service import METHOD_OUT, ServiceError

        try:
            result = self._api.call(method_name, parameters.unpack())
            signature = METHOD_OUT[method_name]
            if signature is None:
                invocation.return_value(None)
            else:
                invocation.return_value(self._glib.Variant(signature, result))
        except ServiceError as exc:
            invocation.return_dbus_error(exc.error_name, str(exc))
        except Exception:
            invocation.return_dbus_error(f"{INTERFACE}.Error.Failed", "internal error")

    def _get_property(
        self,
        _connection: Any,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        property_name: str,
    ) -> Any:
        from tetherbot.service import PROPERTY_TYPES

        value = self._api.properties()[property_name]
        return self._glib.Variant(PROPERTY_TYPES[property_name], value)

    def _set_property(self, *_args: Any) -> None:
        raise RuntimeError("properties are read-only")

    def _on_api_signal(self, name: str, args: tuple[Any, ...]) -> None:
        from tetherbot.service import PROPERTY_TYPES, SIGNAL_SIGNATURES

        if self._connection is None:
            return
        if name == "PropertiesChanged":
            changed = {
                prop: self._glib.Variant(PROPERTY_TYPES[prop], self._api.properties()[prop])
                for prop in args[0]
            }
            parameters = self._glib.Variant("(sa{sv}as)", (INTERFACE, changed, []))
            self._connection.emit_signal(
                None,
                OBJECT_PATH,
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                parameters,
            )
            return
        signature = SIGNAL_SIGNATURES[name]
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            INTERFACE,
            name,
            self._glib.Variant(signature, args),
        )

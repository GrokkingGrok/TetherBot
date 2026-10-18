# SPDX-License-Identifier: GPL-2.0-or-later
"""Export the interface on a private session bus.

The service loop runs on one thread and the client call runs on another,
with a hard timeout around the whole process so a stuck bus cannot hang CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from io import StringIO
from pathlib import Path
from threading import Event, Thread

from tetherbot.dbus_service import BUS_NAME, INTERFACE, OBJECT_PATH

ROOT = Path(__file__).resolve().parents[1]


def test_private_session_bus(tmp_path: Path) -> None:
    if shutil.which("dbus-run-session") is None:
        _skip("dbus-run-session is not installed")
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: F401
    except (ImportError, ValueError):
        _skip("PyGObject Gio is not available")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "bridge"), str(ROOT)))
    env["TETHER_TMP"] = str(tmp_path)
    result = subprocess.run(
        ["dbus-run-session", "--", sys.executable, str(Path(__file__))],
        cwd=ROOT,
        env=env,
        timeout=20,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _skip(reason: str) -> None:
    import pytest

    pytest.skip(reason)


def serve() -> int:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    from tests.helpers import NOW, make_item
    from tetherbot.daemon import BridgeDaemon
    from tetherbot.dbus_service import SessionExport

    tmp = Path(os.environ["TETHER_TMP"])
    (tmp / "config.toml").write_text(
        'schema = "tetherbot/1"\n[bridge]\nmode = "webhook-only"\n',
        encoding="utf-8",
    )
    daemon = BridgeDaemon(
        config_path=tmp / "config.toml",
        state_dir=tmp / "state",
        log_stream=StringIO(),
        clock=lambda: NOW,
    )
    daemon.start()
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin("feed", [make_item()], now=NOW)
    ready = Event()
    failed: list[str] = []
    holder: dict[str, object] = {}

    def _thread() -> None:
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            export = SessionExport(daemon.api)
            export.acquire()
            loop = GLib.MainLoop.new(context, False)
            holder["export"] = export
            holder["loop"] = loop
            holder["context"] = context
            ready.set()
            loop.run()
        except Exception as exc:
            failed.append(f"{exc.__class__.__name__}: {exc}")
            ready.set()
        finally:
            context.pop_thread_default()

    thread = Thread(target=_thread, daemon=True)
    thread.start()
    if not ready.wait(5) or failed:
        print(failed[0] if failed else "service thread did not become ready", file=sys.stderr)
        return 1
    client = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    try:
        if not _owned(client, Gio, GLib):
            print("name is not owned", file=sys.stderr)
            return 1
        items = _call(client, Gio, GLib, "GetItems", "(s)", ("{}",), "(s)")
        parsed = json.loads(items.unpack()[0])
        if [row["key"] for row in parsed] != ["primary/sample-01"]:
            print(parsed, file=sys.stderr)
            return 1
        intro = client.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            "org.freedesktop.DBus.Introspectable",
            "Introspect",
            None,
            GLib.VariantType("(s)"),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
        if "PerformAction" not in intro.unpack()[0]:
            print("introspection missing PerformAction", file=sys.stderr)
            return 1
        state = client.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", (INTERFACE, "State")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
        if state.unpack()[0] != "unconfigured":
            print(state.unpack(), file=sys.stderr)
            return 1
        try:
            _call(client, Gio, GLib, "GetItem", "(s)", ("missing/nope",), "(s)")
        except GLib.Error as exc:
            if "NotFound" not in str(exc):
                print(exc, file=sys.stderr)
                return 1
        else:
            print("GetItem should have failed", file=sys.stderr)
            return 1
    finally:
        context = holder.get("context")
        if context is not None:
            source = GLib.idle_source_new()

            def _stop(*_args: object) -> bool:
                export = holder["export"]
                loop = holder["loop"]
                export.release()  # type: ignore[attr-defined]
                loop.quit()  # type: ignore[attr-defined]
                return GLib.SOURCE_REMOVE

            source.set_callback(_stop)
            source.attach(context)
        thread.join(5)
    return 0


def _owned(client: object, gio: object, glib: object) -> bool:
    reply = client.call_sync(  # type: ignore[attr-defined]
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        glib.Variant("(s)", (BUS_NAME,)),  # type: ignore[attr-defined]
        glib.VariantType("(b)"),  # type: ignore[attr-defined]
        gio.DBusCallFlags.NONE,  # type: ignore[attr-defined]
        3000,
        None,
    )
    return bool(reply.unpack()[0])


def _call(
    client: object,
    gio: object,
    glib: object,
    method: str,
    in_sig: str,
    args: tuple[object, ...],
    out_sig: str,
) -> object:
    return client.call_sync(  # type: ignore[attr-defined]
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE,
        method,
        glib.Variant(in_sig, args),  # type: ignore[attr-defined]
        glib.VariantType(out_sig),  # type: ignore[attr-defined]
        gio.DBusCallFlags.NONE,  # type: ignore[attr-defined]
        3000,
        None,
    )


if __name__ == "__main__":
    raise SystemExit(serve())

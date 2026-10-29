# SPDX-License-Identifier: GPL-2.0-or-later
"""OpenWindow must return without waiting for the window process."""

import pytest

from tetherbot.window_launch import launch_window


def test_launch_window_rejects_a_non_string():
    assert launch_window(None) is False  # type: ignore[arg-type]


def test_launch_window_returns_without_waiting_for_activation(monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio

    seen: dict[str, object] = {}

    class _Bus:
        def call_sync(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("OpenWindow waited on ActivateAction")

        def call(self, *args: object, **_kwargs: object) -> None:
            seen["method"] = args[3]
            seen["name"] = args[0]
            seen["sent"] = True

    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: _Bus())
    assert launch_window("primary/sample-01") is True
    assert seen["method"] == "ActivateAction"
    assert seen["name"] == "io.github.grokkinggrok.TetherBot"
    assert seen["sent"] is True


def test_a_stale_list_load_does_not_finish_the_newer_request(monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio

    from tetherbot.window import BridgeClient

    class _Reply:
        def __init__(self, payload: tuple[object, ...]) -> None:
            self._payload = payload

        def unpack(self) -> tuple[object, ...]:
            return self._payload

    class _Proxy:
        def __init__(self) -> None:
            self.pending: list[tuple[str, object]] = []

        def connect(self, *_args: object, **_kwargs: object) -> int:
            return 1

        def get_cached_property(self, _name: str) -> None:
            return None

        def call(self, method: str, *_args: object) -> None:
            callback = _args[-1]
            self.pending.append((method, callback))

        def call_finish(self, result: _Reply) -> _Reply:
            return result

    proxies: list[_Proxy] = []
    ready: list[object] = []

    def _new(*_args: object) -> None:
        ready.append(_args[-1])
        proxies.append(_Proxy())

    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(Gio.DBusProxy, "new", _new)
    monkeypatch.setattr(Gio.DBusProxy, "new_finish", lambda result: result)

    client = BridgeClient()
    first: list[object] = []
    second: list[object] = []
    client.load_list({"view": "all"}, lambda *args: first.append(args))
    client.load_list({"view": "today"}, lambda *args: second.append(args))
    assert len(ready) == 2

    ready[0](None, proxies[0])
    assert proxies[0].pending == []
    assert first == []

    ready[1](None, proxies[1])
    method, callback = proxies[1].pending.pop(0)
    assert method == "GetItems"
    callback(proxies[1], _Reply(('[{"key": "primary/one"}]',)))
    method, callback = proxies[1].pending.pop(0)
    assert method == "GetTags"
    callback(proxies[1], _Reply(("[]",)))

    assert first == []
    assert second
    items, tags, bots, error = second[0]
    assert items == [{"key": "primary/one"}]
    assert tags == []
    assert bots == []
    assert error is None


def test_launch_window_reports_a_bus_that_rejects_the_request(monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    class _Bus:
        def call(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("activation refused")

    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: _Bus())
    assert launch_window("primary/sample-01") is False


def test_a_dead_window_name_is_started_once_and_the_action_is_sent_again(monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio

    class _Result:
        def __init__(self, ok: bool) -> None:
            self.ok = ok

    class _Reply:
        def __init__(self, payload: tuple[object, ...]) -> None:
            self._payload = payload

        def unpack(self) -> tuple[object, ...]:
            return self._payload

    class _Bus:
        def __init__(self, owned: bool) -> None:
            self.owned = owned
            self.calls: list[tuple[object, object]] = []

        def call(self, *args: object, **_kwargs: object) -> None:
            method = args[3]
            callback = args[-1]
            self.calls.append((args[0], method))
            if method == "NameHasOwner":
                callback(self, _Reply((self.owned,)))
                return
            if method == "ActivateAction" and sum(item[1] == method for item in self.calls) == 1:
                callback(self, _Result(False))
                return
            if method == "StartServiceByName":
                assert args[4].unpack() == ("io.github.grokkinggrok.TetherBot", 0)
                callback(self, _Result(True))
                return
            callback(self, _Result(True))

        def call_finish(self, result: _Result | _Reply) -> _Result | _Reply:
            if isinstance(result, _Reply):
                return result
            if not result.ok:
                raise RuntimeError("activation refused")
            return result

    import tetherbot.window_launch as window_launch

    monkeypatch.setattr(window_launch, "_window_start_sent", False)
    bus = _Bus(False)
    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: bus)
    assert launch_window("clip-tag:c-11111111") is True
    assert bus.calls == [
        ("io.github.grokkinggrok.TetherBot", "ActivateAction"),
        ("org.freedesktop.DBus", "NameHasOwner"),
        ("org.freedesktop.DBus", "StartServiceByName"),
        ("io.github.grokkinggrok.TetherBot", "ActivateAction"),
    ]
    monkeypatch.setattr(window_launch, "_window_start_sent", False)
    owned = _Bus(True)
    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: owned)
    assert launch_window("clip-tag:c-11111111") is True
    assert owned.calls == [
        ("io.github.grokkinggrok.TetherBot", "ActivateAction"),
        ("org.freedesktop.DBus", "NameHasOwner"),
        ("io.github.grokkinggrok.TetherBot", "ActivateAction"),
    ]
    assert ("org.freedesktop.DBus", "StartServiceByName") not in owned.calls


def test_load_clipboard_opens_a_proxy_before_it_reports_the_bridge(monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    from tetherbot.window import BridgeClient

    ready: list[object] = []

    def _new(*args: object) -> None:
        ready.append(args[-1])

    monkeypatch.setattr(Gio, "bus_get_sync", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(Gio.DBusProxy, "new", _new)
    client = BridgeClient()
    reported: list[object] = []
    client.load_clipboard(lambda entries, error: reported.append((entries, error)))
    assert reported == []
    assert len(ready) == 1


def test_proxy_failure_names_the_bridge_only_when_that_name_is_free():
    gi = pytest.importorskip("gi")
    gi.require_version("GLib", "2.0")

    from types import SimpleNamespace

    from tetherbot.window import BridgeClient

    client = BridgeClient()
    client.bridge_name_owned = lambda: True  # type: ignore[method-assign]
    owned = client._proxy_failure(SimpleNamespace(message="the bus timed out"))
    assert str(owned) == "the bus timed out"
    gone = client._proxy_failure(SimpleNamespace(message="Name has no owner"))
    assert str(gone) == "Bridge not running"
    client.bridge_name_owned = lambda: False  # type: ignore[method-assign]
    missing = client._proxy_failure(SimpleNamespace(message="the bus timed out"))
    assert str(missing) == "Bridge not running"
    client.bridge_name_owned = lambda: True  # type: ignore[method-assign]
    unnamed = client._proxy_failure(None)
    assert str(unnamed) == "The bridge did not answer."

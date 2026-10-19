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

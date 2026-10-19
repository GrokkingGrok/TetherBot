# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke the TetherBot window against a fake bridge client."""

import os

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, GLib, Gtk
except ValueError as exc:
    pytest.skip(str(exc), allow_module_level=True)

if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    pytest.skip("GTK window test needs a display", allow_module_level=True)

from tetherbot.markdown import render  # noqa: E402
from tetherbot.window import WindowApp, apply_runs  # noqa: E402


class _Fake:
    def __init__(self) -> None:
        self.specs: list[dict] = []
        self.done: list[str] = []
        self.undone: list[str] = []
        self.notes: list[str] = []
        self.items = [
            {
                "key": "primary/one",
                "kind": "todo",
                "title": "Pack the bag",
                "body": (
                    "# Hello\n\nSee [the note](https://example.test/note).\n\n"
                    "![cat](https://example.test/cat.png)"
                ),
                "body_format": "markdown",
                "status": "open",
                "actions": ["done"],
                "chips": {
                    "priority": {"label": "#1", "tone": "red"},
                    "due": {"label": "Due Sat 10/17 15:00", "tone": "amber"},
                    "created": {"label": "Created 10/17", "tone": "green"},
                    "tags": [{"tag": "home", "label": "@home", "tone": "teal"}],
                },
                "source": {"bot": "primary", "routine": "daily"},
                "updated_at": "2026-10-17T11:40:00+00:00",
            }
        ]

    def set_listener(self, listener) -> None:
        self.listener = listener

    def get_items(self, spec):
        self.specs.append(spec)
        return list(self.items)

    def get_tags(self):
        return [{"tag": "home", "count": 1, "color": "teal"}]

    def bots(self):
        return [{"name": "primary", "routes": {"outbound": True}}]

    def get_item(self, key):
        for item in self.items:
            if item["key"] == key:
                return item
        raise AssertionError(key)

    def mark_done(self, key):
        self.done.append(key)
        return "a-done"

    def undo(self, key):
        self.undone.append(key)
        return {"result": "dropped"}

    def send_note(self, key):
        self.notes.append(key)
        return "a-note"


def test_window_filters_renders_markdown_and_undoes():
    opened: list[str] = []
    fake = _Fake()
    app = WindowApp(client=fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window.open_uri = opened.append
            assert fake.specs[0]["kinds"] == ["todo"]
            assert fake.specs[0]["status"] == "open"
            assert fake.specs[0]["view"] == "all"
            window.select_key("primary/one")
            text = window.buffer.get_text(
                window.buffer.get_start_iter(),
                window.buffer.get_end_iter(),
                True,
            )
            assert "Hello" in text
            assert "the note" in text
            assert "cat" in text
            assert "example.test/cat.png" not in text
            assert "**" not in text
            assert "https://example.test/note" in window._link_tags
            assert window.source.get_label().startswith("primary · daily ·")
            assert window.done_button.get_sensitive()
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
            found = window.buffer.get_start_iter().forward_search(
                "the note",
                Gtk.TextSearchFlags.TEXT_ONLY,
                None,
            )
            assert found is not None
            start, _end = found
            rect = window.text.get_iter_location(start)
            point = window.text.buffer_to_window_coords(
                Gtk.TextWindowType.WIDGET,
                rect.x + max(rect.width // 2, 1),
                rect.y + max(rect.height // 2, 1),
            )
            pos_x, pos_y = point[0], point[1]
            window._on_text_click(None, 1, pos_x, pos_y)
            assert opened == ["https://example.test/note"]
            window.search.set_text("@home due:today")
            assert fake.specs[-1]["query"] == "@home due:today"
            window.show_done.set_active(True)
            assert fake.specs[-1]["include_done_days"] == 7
            assert "status" not in fake.specs[-1]
            window._on_key(None, Gdk.KEY_f, 0, Gdk.ModifierType.CONTROL_MASK)
            focus = window.get_focus()
            assert focus is window.search or (
                focus is not None and focus.is_ancestor(window.search)
            )
            window._on_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.CONTROL_MASK)
            assert fake.done == ["primary/one"]
            window._undo("primary/one")
            assert fake.undone == ["primary/one"]
            window._ask_current()
            assert fake.notes == ["primary/one"]
            window.split.set_collapsed(True)
            assert window.back.get_visible()
            runs = render("[docs](https://example.test/docs)")
            apply_runs(window.buffer, runs, window._link_tags)
            assert "https://example.test/docs" in window._link_tags
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: GLib.idle_add(finish))
    GLib.timeout_add(8000, app.quit)
    app.run(["tetherbot-window"])
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True

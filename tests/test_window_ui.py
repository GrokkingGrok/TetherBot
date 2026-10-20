# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke the TetherBot window against a fake bridge client."""

import os

import pytest

from tests.helpers import reset_tetherbot_logger


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
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gdk, GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    try:
        from tetherbot.markdown import render
        from tetherbot.window import WindowApp, apply_runs

        opened: list[str] = []
        fake = _Fake()
        app = WindowApp(client=fake)
        holder: dict = {}
        _exercise_window(app, fake, opened, holder, Gdk, GLib, Gtk, render, apply_runs)
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _exercise_window(app, fake, opened, holder, gdk, glib, gtk, render, apply_runs) -> None:

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
            context = glib.MainContext.default()
            while context.pending():
                context.iteration(False)
            found = window.buffer.get_start_iter().forward_search(
                "the note",
                gtk.TextSearchFlags.TEXT_ONLY,
                None,
            )
            assert found is not None
            start, _end = found
            rect = window.text.get_iter_location(start)
            point = window.text.buffer_to_window_coords(
                gtk.TextWindowType.WIDGET,
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
            window._on_key(None, gdk.KEY_f, 0, gdk.ModifierType.CONTROL_MASK)
            focus = window.get_focus()
            assert focus is window.search or (
                focus is not None and focus.is_ancestor(window.search)
            )
            window._on_key(None, gdk.KEY_Return, 0, gdk.ModifierType.CONTROL_MASK)
            assert fake.done == ["primary/one"]
            window._undo("primary/one")
            assert fake.undone == ["primary/one"]
            window._ask_current()
            assert fake.notes == ["primary/one"]
            assert window.close_detail.get_visible()
            assert not window.close_sidebar.get_visible()
            window.split.set_collapsed(True)
            assert window.back.get_visible()
            window.split.set_show_content(True)
            assert window.close_detail.get_visible()
            assert not window.close_sidebar.get_visible()
            window.split.set_show_content(False)
            assert window.close_sidebar.get_visible()
            assert not window.close_detail.get_visible()
            window.search.set_text("keep")
            closed: list[bool] = []
            window.close = lambda: closed.append(True)
            assert window._on_key(None, gdk.KEY_Escape, 0, gdk.ModifierType(0))
            assert window.search.get_text() == "keep"
            assert window._on_key(None, gdk.KEY_w, 0, gdk.ModifierType.CONTROL_MASK)
            assert closed == [True, True]
            runs = render("[docs](https://example.test/docs)")
            apply_runs(window.buffer, runs, window._link_tags)
            assert "https://example.test/docs" in window._link_tags
            app._on_close(window)
            assert app.window is None
            assert app._linger
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: glib.idle_add(finish))
    glib.timeout_add(8000, app.quit)
    app.run(["tetherbot-window"])


class _TimerFake(_Fake):
    def __init__(self) -> None:
        super().__init__()
        self.items[0]["time_tracked_s"] = 3600 + 42 * 60
        self.items.append(
            {
                "key": "primary/two",
                "kind": "todo",
                "title": "Email venue about deposit",
                "body": "Hold the date.",
                "status": "open",
                "actions": ["done"],
                "source": {"bot": "primary"},
            }
        )
        self.timer: dict = {"state": "idle"}
        self.started: list[str] = []
        self.stopped = 0

    def get_timer(self):
        return dict(self.timer)

    def start_timer(self, key):
        self.started.append(key)
        title = next((item["title"] for item in self.items if item["key"] == key), key)
        self.timer = {"state": "running", "item_key": key, "item_title": title}
        return dict(self.timer)

    def stop_timer(self):
        self.stopped += 1
        previous = self.timer.get("item_title") or "Timer"
        self.timer = {"state": "idle", "item_title": previous}
        return dict(self.timer)


def test_window_starts_a_timer_and_asks_before_switching():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    try:
        from tetherbot.window import WindowApp

        fake = _TimerFake()
        app = WindowApp(client=fake)
        holder: dict = {}
        _exercise_timer(app, fake, holder, GLib)
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _exercise_timer(app, fake, holder, glib) -> None:
    def finish():
        try:
            window = app.window
            assert window is not None
            assert window.get_icon_name() == "io.github.grokkinggrok.TetherBot"
            window.select_key("primary/one")
            assert window.start_button.get_visible()
            assert window.start_button.get_label() == "Start timer"
            assert _has_label(window.detail_chips, "1:42 tracked")
            assert _has_label(window.list, "1:42 tracked")
            play = _find_play(window.list, "Start timer: Pack the bag")
            assert play is not None
            play.emit("clicked")
            assert fake.started == ["primary/one"]
            assert _has_label(window.list, "Timing")
            assert window.start_button.get_label() == "Timing"
            assert not window.start_button.get_sensitive()
            other = _find_play(window.list, "Start timer: Email venue about deposit")
            assert other is not None
            other.emit("clicked")
            assert window.switch_box.get_visible()
            assert window.switch_label.get_label() == (
                "Stop Pack the bag and start this one?"
            )
            assert fake.started == ["primary/one"]
            window.switch_cancel.emit("clicked")
            assert not window.switch_box.get_visible()
            other.emit("clicked")
            window.switch_button.emit("clicked")
            assert fake.stopped == 1
            assert fake.started == ["primary/one", "primary/two"]
            assert not window.switch_box.get_visible()
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: glib.idle_add(finish))
    glib.timeout_add(8000, app.quit)
    app.run(["tetherbot-window"])


class _EditFake(_TimerFake):
    def __init__(self) -> None:
        super().__init__()
        self.timer = {
            "state": "stopped",
            "elapsed_s": 41 * 60,
            "item_key": "",
            "item_title": "",
        }
        self.adjusted: list[int] = []
        self.starts: list[int] = []
        self.attached: list[str] = []
        self.dismissed = 0

    def adjust_start(self, delta):
        self.adjusted.append(delta)
        elapsed = int(self.timer.get("elapsed_s") or 0) - delta
        self.timer = {
            "state": "running",
            "item_key": "",
            "item_title": "",
            "elapsed_s": elapsed,
        }
        return dict(self.timer)

    def set_start(self, started_at):
        self.starts.append(started_at)
        self.timer = {
            "state": "running",
            "item_key": "",
            "item_title": "",
            "elapsed_s": 5 * 60,
        }
        return dict(self.timer)

    def attach_timer(self, key):
        self.attached.append(key)
        self.timer = {"state": "idle"}
        return dict(self.timer)

    def dismiss_timer(self):
        self.dismissed += 1
        self.timer = {"state": "idle"}
        return dict(self.timer)


def test_window_edits_a_start_and_keeps_a_stopped_timer():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    try:
        from tetherbot.window import WindowApp

        fake = _EditFake()
        app = WindowApp(client=fake)
        holder: dict = {}
        _exercise_edit(app, fake, holder, GLib)
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _exercise_edit(app, fake, holder, glib) -> None:
    def finish():
        try:
            window = app.window
            assert window is not None
            window.select_key("primary/one")
            assert window.timer_label.get_label() == "Stopped, unassigned · 41m"
            assert window.attach_button.get_visible()
            window.attach_button.emit("clicked")
            assert fake.attached == ["primary/one"]
            assert not window.timer_box.get_visible()
            fake.timer = {
                "state": "running",
                "item_key": "",
                "item_title": "",
                "elapsed_s": 5 * 60,
            }
            window._request_timer()
            assert window.timer_label.get_label() == "Timer running · 5m"
            assert window.attach_button.get_visible()
            edit = _find_button(window.timer_actions, "Edit start")
            assert edit is not None
            edit.emit("clicked")
            assert window.edit_start_box.get_visible()
            shift = _find_button(window.edit_start_box, "-5m")
            assert shift is not None
            shift.emit("clicked")
            assert fake.adjusted == [-300]
            assert window.timer_label.get_label() == "Timer running · 10m"
            window._set_editing_start(True)
            window.start_entry.set_text("nope")
            window._on_set_start()
            assert fake.starts == []
            window.start_entry.set_text("09:30")
            window._on_set_start()
            assert len(fake.starts) == 1
            assert isinstance(fake.starts[0], int)
            fake.timer = {
                "state": "stopped",
                "elapsed_s": 41 * 60,
                "item_key": "",
                "item_title": "",
            }
            window._request_timer()
            other = _find_play(window.list, "Start timer: Email venue about deposit")
            assert other is not None
            other.emit("clicked")
            assert window.switch_label.get_label() == (
                "Discard the stopped time and start this one?"
            )
            window.switch_button.emit("clicked")
            assert fake.dismissed == 1
            assert fake.started[-1] == "primary/two"
            fake.timer = {
                "state": "running",
                "item_key": "",
                "item_title": "",
                "elapsed_s": 60,
            }
            window._request_timer()
            window._start_timer("primary/one", "Pack the bag")
            assert window.switch_label.get_label() == "Stop Timer and start this one?"
            window.switch_button.emit("clicked")
            assert fake.stopped == 1
            assert fake.dismissed == 2
            assert fake.started[-1] == "primary/one"
            fake.timer = {
                "state": "stopped",
                "elapsed_s": 41 * 60,
                "item_key": "",
                "item_title": "",
            }
            window._request_timer()
            dismiss = _find_button(window.timer_actions, "Dismiss")
            assert dismiss is not None
            dismiss.emit("clicked")
            assert fake.dismissed == 3
            assert not window.timer_box.get_visible()
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: glib.idle_add(finish))
    glib.timeout_add(8000, app.quit)
    app.run(["tetherbot-window"])


def _find_button(widget, label: str):
    if hasattr(widget, "get_label") and widget.get_label() == label:
        return widget
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        found = _find_button(child, label)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _has_label(widget, text: str) -> bool:
    if hasattr(widget, "get_label") and widget.get_label() == text:
        return True
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        if _has_label(child, text):
            return True
        child = child.get_next_sibling()
    return False


def _find_play(widget, tooltip: str):
    if hasattr(widget, "get_tooltip_text") and widget.get_tooltip_text() == tooltip:
        return widget
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        found = _find_play(child, tooltip)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None

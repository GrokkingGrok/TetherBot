# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke the TetherBot window against a fake bridge client."""

import logging
import os
import time

import pytest

from tests.helpers import reset_tetherbot_logger


class _Fake:
    def __init__(self) -> None:
        self.specs: list[dict] = []
        self.done: list[str] = []
        self.done_notes: list[str] = []
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
                    "priority": {"label": "High priority", "tone": "red"},
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

    def mark_done(self, key, note=""):
        self.done.append(key)
        self.done_notes.append(note)
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
            from tetherbot.ui_settings import resolve_ui_settings

            seconds = resolve_ui_settings(None).done_history_seconds
            if seconds:
                assert fake.specs[-1]["include_done_seconds"] == seconds
            else:
                assert "include_done_seconds" not in fake.specs[-1]
            assert "include_done_days" not in fake.specs[-1]
            assert "status" not in fake.specs[-1]
            window._on_key(None, gdk.KEY_f, 0, gdk.ModifierType.CONTROL_MASK)
            focus = window.get_focus()
            assert focus is window.search or (
                focus is not None and focus.is_ancestor(window.search)
            )
            window._on_key(None, gdk.KEY_Return, 0, gdk.ModifierType.CONTROL_MASK)
            assert fake.done == []
            assert "primary/one" in window._undo_holds
            window._undo("primary/one")
            assert fake.done == []
            assert fake.undone == []
            window._on_key(None, gdk.KEY_Return, 0, gdk.ModifierType.CONTROL_MASK)
            assert fake.done == []
            window._on_window_close(window)
            assert fake.done == ["primary/one"]
            assert fake.undone == []
            window._ask_current()
            assert fake.notes == ["primary/one"]
            kept = window.list.get_row_at_index(0)
            assert kept is not None
            window._list_hovered = True
            window.refresh()
            assert kept.get_visible() is False
            assert kept.get_parent() is not None
            drop = window._drop_idle
            assert drop
            window._drop_idle = 0
            glib.source_remove(drop)
            assert window._drop_doomed() == glib.SOURCE_CONTINUE
            assert window._drop_doomed() == glib.SOURCE_REMOVE
            index = 0
            while True:
                current = window.list.get_row_at_index(index)
                if current is None:
                    break
                assert current is not kept
                index += 1
            assert index >= 1
            window._list_hovered = False
            width, height = window.get_default_size()
            assert width >= 1520 and height >= 680
            request_width, request_height = window.get_size_request()
            assert request_width >= 1400 and request_height >= 640
            assert window.toolbar.get_content() is window.toasts
            assert window.get_titlebar() is not window.detail_header
            assert window.titlebar.get_show_end_title_buttons()
            assert not window.detail_header.get_show_end_title_buttons()
            assert not window.detail_header.get_show_start_title_buttons()
            assert not window.detail_header.get_visible()
            window.split.set_collapsed(True)
            assert window.back.get_visible()
            assert window.detail_header.get_visible()
            window.split.set_collapsed(False)
            assert not window.detail_header.get_visible()
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


def test_done_with_note_sends_the_text_and_stays_disabled_when_empty():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    fake = _Fake()
    app = WindowApp(client=fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            assert isinstance(window.note_view, Gtk.TextView)
            assert window.note_view.get_editable()
            assert window.note_label.get_label() == "Note"
            assert window.done_note_button.get_label() == "Done with note"
            window.select_key("primary/one")
            assert window.done_button.get_sensitive()
            assert not window.done_note_button.get_sensitive()
            window.note_buffer.set_text("   ")
            assert not window.done_note_button.get_sensitive()
            window.note_buffer.set_text("Packed the blue bag")
            assert window.done_note_button.get_sensitive()
            window._outbound["primary"] = False
            window._sync_done_note()
            assert not window.done_note_button.get_sensitive()
            window._outbound["primary"] = True
            window._sync_done_note()
            assert window.done_note_button.get_sensitive()
            window.note_buffer.set_text("")
            assert not window.done_note_button.get_sensitive()
            window._done_current()
            assert "note" not in window._undo_holds["primary/one"]
            assert window._undo_holds["primary/one"]["via"] == "done"
            assert window.done_undo.get_parent() is window.done_stack.get_visible_child()
            assert window.done_note_button.get_parent() is window.note_stack.get_visible_child()
            assert not window.done_note_button.get_sensitive()
            assert window.start_button.get_visible()
            assert window.attach_button.get_visible()
            assert window.copy_button.get_visible()
            assert window.ask_button.get_visible()
            window._undo("primary/one")
            assert window.done_button.get_parent() is window.done_stack.get_visible_child()
            assert window.done_note_button.get_parent() is window.note_stack.get_visible_child()
            window.note_buffer.set_text("Packed the blue bag")
            window.done_note_button.emit("clicked")
            assert window._undo_holds["primary/one"]["via"] == "note"
            assert window.note_undo.get_parent() is window.note_stack.get_visible_child()
            assert window.done_button.get_parent() is window.done_stack.get_visible_child()
            assert not window.done_button.get_sensitive()
            assert window.start_button.get_visible()
            assert window.attach_button.get_visible()
            assert window._undo_holds["primary/one"]["note"] == "Packed the blue bag"
            assert window._note_text() == ""
            assert not window.done_note_button.get_sensitive()
            window._on_window_close(window)
            assert fake.done == ["primary/one"]
            assert fake.done_notes == ["Packed the blue bag"]
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: GLib.idle_add(finish))
    GLib.timeout_add(8000, app.quit)
    try:
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_failed_send_leaves_the_hovered_row_until_a_later_idle():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import BridgeError, WindowApp

    class _Down(_Fake):
        def mark_done(self, key, note=""):
            self.done.append(key)
            self.done_notes.append(note)
            raise BridgeError("could not send")

    fake = _Down()
    app = WindowApp(client=fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window.select_key("primary/one")
            window._done_current()
            row = window._rows["primary/one"]
            window._undo_holds["primary/one"]["until"] = 0
            window._list_hovered = True
            window._flush_due(False)
            assert fake.done == ["primary/one"]
            assert row.get_parent() is not None
            assert row.get_visible()
            assert "primary/one" in window._undo_holds
            assert window._undo_holds["primary/one"].get("failed") is True
            first = window._after_send_idle
            assert first
            window._schedule_after_send()
            assert window._after_send_idle == first
            assert window._after_send() == GLib.SOURCE_REMOVE
            assert row.get_parent() is not None
            assert row.get_visible()
            assert "primary/one" in window._undo_holds
            waiting = window._after_send_idle
            assert waiting
            GLib.source_remove(waiting)
            window._after_send_idle = 0
            window._list_hovered = False
            window._schedule_after_send()
            assert window._after_send() == GLib.SOURCE_REMOVE
            assert "primary/one" not in window._undo_holds
            assert any(item.get("key") == "primary/one" for item in window._items)
            assert window._rows["primary/one"].get_parent() is not None
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: GLib.idle_add(finish))
    GLib.timeout_add(8000, app.quit)
    try:
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_detail_buttons_stay_short_and_inside_the_pane():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    fake = _Fake()
    app = WindowApp(client=fake)
    holder: dict = {}

    def finish():
        window = app.window
        assert window is not None
        window.present()
        window.select_key("primary/one")

        def check(width: int, nxt):
            window.set_default_size(width, 800)

            def measure():
                try:
                    _assert_action_row(window, Gtk)
                    if nxt is None:
                        holder["ok"] = True
                        app.quit()
                    else:
                        nxt()
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()
                return False

            GLib.timeout_add(200, measure)

        def at_1400():
            check(1400, None)

        check(1520, at_1400)
        return False

    app.connect("activate", lambda _app: GLib.idle_add(finish))
    GLib.timeout_add(8000, app.quit)
    try:
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _assert_action_row(window, gtk) -> None:
    buttons = (
        window.done_button,
        window.done_note_button,
        window.start_button,
        window.attach_button,
        window.copy_button,
        window.ask_button,
    )
    pane = window.action_row.get_parent()
    assert pane is not None
    pane_width = pane.get_width()
    assert pane_width > 0
    assert window.action_row.get_width() <= pane_width
    assert not window.action_row.get_vexpand()
    # One line when the labels fit. A narrower pane wraps. Text scale changes
    # the width, so the height has to match the row's own measure.
    one_line = window.action_row.measure(gtk.Orientation.VERTICAL, 4000).natural
    at_width = window.action_row.measure(
        gtk.Orientation.VERTICAL, max(window.action_row.get_width(), 1)
    ).natural
    narrow = window.action_row.measure(gtk.Orientation.VERTICAL, 320).natural
    assert 24 <= one_line
    assert narrow > one_line
    assert window.action_row.get_height() == at_width
    labels = window.action_row.measure(gtk.Orientation.HORIZONTAL, -1).natural
    if window.action_row.get_width() >= labels:
        assert window.action_row.get_height() == one_line
    body = window.text.get_parent().get_parent()
    assert body.get_vexpand()
    assert body.get_height() > window.action_row.get_height()
    for button in buttons:
        assert 16 <= button.get_height() <= window.action_row.get_height()
        found, bounds = button.compute_bounds(window.action_row)
        assert found
        assert bounds.get_x() >= -1
        right = bounds.get_x() + bounds.get_width()
        assert right <= window.action_row.get_width() + 1
    widths = []
    gaps = []
    previous = None
    for button in buttons:
        found, bounds = button.compute_bounds(window.action_row)
        widths.append(round(bounds.get_width()))
        if previous is not None and abs(previous.get_y() - bounds.get_y()) < 2:
            gap = bounds.get_x() - (previous.get_x() + previous.get_width())
            gaps.append(round(gap))
        previous = bounds
    assert len(set(widths)) > 1
    assert len(gaps) >= 1
    assert max(gaps) - min(gaps) <= 1
    start_before = _button_x(window, window.start_button)
    ask_before = _button_x(window, window.ask_button)
    window._done_current()
    assert window.done_undo.get_parent() is window.done_stack.get_visible_child()
    assert _button_x(window, window.start_button) == start_before
    assert _button_x(window, window.ask_button) == ask_before
    window._undo("primary/one")


def _button_x(window, button) -> int:
    found, bounds = button.compute_bounds(window.action_row)
    assert found
    return round(bounds.get_x())


def test_done_row_clears_when_another_todo_is_selected():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    class _Sent(_Fake):
        def __init__(self) -> None:
            super().__init__()
            self.items.append(
                {
                    "key": "primary/two",
                    "kind": "todo",
                    "title": "Second item",
                    "body": "Leave this one open.",
                    "status": "open",
                    "actions": ["done"],
                    "source": {"bot": "primary"},
                }
            )

        def mark_done(self, key, note=""):
            self.done.append(key)
            self.done_notes.append(note)
            self.items = [item for item in self.items if item.get("key") != key]
            return "a-done"

    fake = _Sent()
    app = WindowApp(client=fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window.select_key("primary/one")
            window._done_current()
            other = window._rows["primary/two"]
            other.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
            window.list.select_row(other)
            window._list_hovered = True
            window._undo_holds["primary/one"]["until"] = 0
            window._flush_due(False)
            assert fake.done == ["primary/one"]
            pending = window._after_send_idle
            assert pending
            GLib.source_remove(pending)
            window._after_send_idle = 0
            assert window._after_send() == GLib.SOURCE_REMOVE
            assert "primary/one" not in window._undo_holds
            assert "primary/one" not in window._rows
            assert other.get_parent() is not None
            assert window._rows["primary/two"].get_visible()
            assert window._current.get("key") == "primary/two"
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    app.connect("activate", lambda _app: GLib.idle_add(finish))
    GLib.timeout_add(8000, app.quit)
    try:
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


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

    def get_item_time(self, key):
        item = next(row for row in self.items if row["key"] == key)
        total = int(item.get("time_tracked_s") or 0)
        records = []
        if total:
            records.append({"id": "rec-1", "seconds": total, "at": 0, "kind": "session"})
        return {"item_key": key, "total_s": total, "records": records}

    def set_tracked_total(self, key, total_s):
        for item in self.items:
            if item["key"] == key:
                item["time_tracked_s"] = total_s
        return self.get_item_time(key)

    def delete_time_record(self, key, record_id):
        self.deleted = [key, record_id]
        for item in self.items:
            if item["key"] == key:
                item["time_tracked_s"] = 0
        return {"item_key": key, "total_s": 0, "records": []}


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
            assert window.time_box.get_visible()
            assert window.time_entry.get_text() == "1:42:00"
            assert _has_label(window.time_records, "1:42:00")
            window.time_entry.set_text("1:00:00")
            window.time_set.emit("clicked")
            assert fake.items[0]["time_tracked_s"] == 3600
            assert window.time_entry.get_text() == "1:00:00"
            trash = _find_play(window.time_records, "Delete time record")
            assert trash is not None
            trash.emit("clicked")
            dialog = window._time_dialog
            assert dialog is not None
            assert dialog.get_heading() == "Delete this time record?"
            dialog.emit("response", "cancel")
            assert not getattr(fake, "deleted", None)
            dialog.emit("response", "delete")
            assert fake.deleted == ["primary/one", "rec-1"]
            assert window.time_entry.get_text() == "0:00:00"
            play = _find_play(window.list, "Start timer: Pack the bag")
            assert play is not None
            play.emit("clicked")
            assert fake.started == ["primary/one"]
            assert _has_label(window.list, "Timing")
            assert window.start_button.get_label() == "Stop timer"
            assert window.start_button.get_sensitive()
            assert window.copy_button.get_label() == "Copy Todo"
            assert window.copy_title_button.get_tooltip_text() == "Copy title"
            assert window.copy_title_button.get_sensitive()
            assert window.copy_body_button.get_tooltip_text() == "Copy body"
            assert window.copy_body_button.get_sensitive()
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
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gdk, GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    try:
        from tetherbot.window import WindowApp

        fake = _EditFake()
        app = WindowApp(client=fake)
        holder: dict = {}
        _exercise_edit(app, fake, holder, GLib, Gdk)
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _exercise_edit(app, fake, holder, glib, gdk) -> None:
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
            shift_labels: list[str] = []
            shift_child = window.edit_start_box.get_first_child()
            while shift_child is not None:
                shift_text = shift_child.get_label() if hasattr(shift_child, "get_label") else None
                if shift_text:
                    shift_labels.append(shift_text)
                shift_child = shift_child.get_next_sibling()
            assert shift_labels.index("-1m") < shift_labels.index("-5m")
            shift = _find_button(window.edit_start_box, "-5m")
            assert shift is not None
            shift.emit("clicked")
            assert fake.adjusted == [-300]
            assert window.timer_label.get_label() == "Timer running · 10m"
            window._set_editing_start(True)
            window.start_entry.set_text("nope")
            window.start_entry.emit("activate")
            assert fake.starts == []
            window.start_entry.set_text("09:30")
            window.set_focus(window.start_entry)
            focus = window.get_focus()
            assert focus is not None and (
                focus is window.start_entry or focus.is_ancestor(window.start_entry)
            )
            assert window._on_key(None, gdk.KEY_Return, 0, gdk.ModifierType(0)) is False
            window.start_entry.emit("activate")
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


class _StoreTimer(_Fake):
    """The window click talks to a real timer file, not a stub that only records."""

    def __init__(self, store) -> None:
        super().__init__()
        self.store = store

    def get_timer(self):
        return self.store.view()

    def attach_timer(self, key):
        title = next((item["title"] for item in self.items if item["key"] == key), "")
        return self.store.attach(key, title)

    def start_timer(self, key):
        title = next((item["title"] for item in self.items if item["key"] == key), "")
        return self.store.start(key, title)

    def stop_timer(self):
        return self.store.stop()


def test_attach_button_click_writes_the_timer(tmp_path):
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
        from tetherbot.timer import TimerStore
        from tetherbot.window import WindowApp

        store = TimerStore(tmp_path)
        store.start("", "")
        store.stop()
        fake = _StoreTimer(store)
        app = WindowApp(client=fake)
        holder: dict = {}
        _exercise_attach_click(app, fake, holder, GLib)
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _exercise_attach_click(app, fake, holder, glib) -> None:
    def finish():
        try:
            window = app.window
            assert window is not None
            window.select_key("primary/one")
            assert window.timer_label.get_label().startswith("Stopped, unassigned")
            assert window.attach_button.get_visible()
            window.attach_button.emit("clicked")
            assert fake.store.view()["state"] == "idle"
            assert not (fake.store.path).exists()
            assert not window.timer_box.get_visible()
            assert window.attach_button.get_visible()
            assert not window.attach_button.get_sensitive()
            fake.store.start("", "")
            window._request_timer()
            assert window.attach_button.get_visible()
            assert window.attach_button.get_sensitive()
            window.attach_button.emit("clicked")
            saved = fake.store.view()
            assert saved["state"] == "running"
            assert saved["item_key"] == "primary/one"
            assert saved["item_title"] == "Pack the bag"
            assert "Pack the bag" in window.timer_label.get_label()
            assert _has_label(window.list, "Timing")
            assert window.attach_button.get_visible()
            assert not window.attach_button.get_sensitive()
            assert window.start_button.get_label() == "Stop timer"
            assert window.start_button.get_sensitive()
            window.start_button.emit("clicked")
            assert fake.store.view()["state"] == "idle"
            assert window.start_button.get_label() == "Start timer"
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


def _label_contains(widget, text: str) -> bool:
    label = widget.get_label() if hasattr(widget, "get_label") else None
    if isinstance(label, str) and text in label:
        return True
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        if _label_contains(child, text):
            return True
        child = child.get_next_sibling()
    return False


def _has_label(widget, text: str) -> bool:
    if hasattr(widget, "get_label") and widget.get_label() == text:
        return True
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        if _has_label(child, text):
            return True
        child = child.get_next_sibling()
    return False


def test_bots_page_filters_by_name_and_a_row_filters_todos():
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

        fake = _Fake()
        fake.items[0]["display_name"] = "Primary"
        fake.bots = lambda: [
            {
                "name": "primary",
                "display_name": "Primary",
                "last_seen": 1_700_000_000,
                "next_run": 0,
                "open_todos": 1,
                "open_asks": 0,
                "state": "idle",
                "routes": {"outbound": True},
            },
            {
                "name": "notes",
                "display_name": "Notes",
                "last_seen": 1_700_000_000,
                "next_run": 0,
                "open_todos": 2,
                "open_asks": 0,
                "state": "needs_you",
                "summary": "Needs a look",
                "routes": {"outbound": False},
            },
        ]
        app = WindowApp(client=fake)
        holder: dict = {}

        def finish():
            try:
                window = app.window
                assert window is not None
                assert window._page_todos.get_active()
                window.select_key("bots")
                assert window._page == "bots"
                assert _label_contains(window.list, "Needs a look")
                assert _has_label(window.list, "●")
                assert window.bot_search.get_visible()
                assert not window._todo_controls.get_visible()
                assert _bot_labels(window) == ["Primary", "Notes"]
                window.bot_search.set_text("note")
                assert _bot_labels(window) == ["Notes"]
                row = window.list.get_row_at_index(0)
                window._on_row_activated(None, row)
                assert window._page == "todos"
                assert fake.specs[-1]["bots"] == ["notes"]
                assert _has_label(window.list, "Primary")
                holder["ok"] = True
            except Exception as exc:
                holder["error"] = exc
            app.quit()
            return False

        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_an_open_window_picks_up_a_renamed_bot():
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
        from tetherbot.window import BridgeClient, WindowApp

        fake = _Fake()
        fake.items[0]["display_name"] = "Primary"
        fake.bot_rows = [
            {
                "name": "primary",
                "display_name": "Primary",
                "state": "idle",
                "summary": "Quiet",
                "last_seen": 1_700_000_000,
                "next_run": 0,
                "open_todos": 1,
                "routes": {"outbound": True},
            }
        ]
        fake.bots = lambda: list(fake.bot_rows)
        app = WindowApp(client=fake)
        holder: dict = {}

        def finish():
            try:
                window = app.window
                assert window is not None
                assert _has_label(window.list, "Primary")
                fake.items[0]["display_name"] = "Desk"
                fake.bot_rows[0]["display_name"] = "Desk"
                fake.bot_rows[0]["state"] = "needs_you"
                fake.bot_rows[0]["summary"] = "Needs a look"
                fake.listener()
                assert _has_label(window.list, "Desk")
                assert not _has_label(window.list, "Primary")
                window.select_key("bots")
                assert _bot_labels(window) == ["Desk"]
                assert _label_contains(window.list, "Needs a look")
                assert _has_label(window.list, "●")
                client = BridgeClient()
                seen: list[str] = []

                def _reload() -> bool:
                    seen.append("reload")
                    return GLib.SOURCE_REMOVE

                client.set_listener(_reload)
                client.note_properties(["LastSync"])
                client.note_properties(["QueueLength", "Counts"])
                client.note_properties(["Bots"])

                def check() -> bool:
                    try:
                        assert seen == ["reload"]
                        holder["ok"] = True
                    except Exception as exc:
                        holder["error"] = exc
                    app.quit()
                    return GLib.SOURCE_REMOVE

                GLib.idle_add(check)
            except Exception as exc:
                holder["error"] = exc
                app.quit()
            return GLib.SOURCE_REMOVE

        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_clipboard_tag_filter_stops_after_one_rebuild():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("Pango", "1.0")
        from gi.repository import Adw, Gio, GLib, Pango
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    class _Clip:
        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return []

        def get_clipboard(self):
            return [
                {
                    "id": "c-11111111",
                    "text": "alpha line",
                    "at": 2,
                    "pinned": False,
                    "tags": [{"name": "Later", "color": "blue"}],
                },
                {
                    "id": "c-22222222",
                    "text": "beta line",
                    "at": 1,
                    "pinned": False,
                    "tags": [],
                },
                {
                    "id": "c-33333333",
                    "text": "hidden-secret",
                    "at": 3,
                    "pinned": True,
                    "masked": True,
                    "tags": [],
                },
                {
                    "id": "c-44444444",
                    "kind": "image",
                    "mime": "image/png",
                    "size": 1258291,
                    "at": 4,
                    "pinned": False,
                    "tags": [{"name": "Shot", "color": "green"}],
                    "text": "",
                    "path": "/tetherbot-missing/clipboard-image.png",
                    "thumb": "/tetherbot-missing/clipboard-image.thumb.png",
                },
            ]

    class _Isolated(WindowApp):
        """A second process must not attach to a window the user already has open."""

        def __init__(self, client: _Clip) -> None:
            Adw.Application.__init__(
                self,
                application_id="io.github.grokkinggrok.TetherBot.ClipboardTest",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self.window = None
            self._linger = 0

    app = _Isolated(_Clip())
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            fills = {"n": 0}
            original = window._fill_clipboard_rows

            def wrapped() -> None:
                fills["n"] += 1
                if fills["n"] > 6:
                    raise AssertionError("tag filter rebuilt without stopping")
                original()

            window._fill_clipboard_rows = wrapped
            window.clip_tag.set_selected(1)
            assert fills["n"] == 1
            assert window._clip_tag == "Later"
            shown = _clip_rows(window)
            assert [row.clip_text for row in shown] == ["alpha line"]
            assert _clip_marks(window) == ["Pinned", "|", "Unpinned", "c-11111111"]
            assert all(getattr(row, "clip_kind", "") != "image" for row in shown)
            window.clip_tag.set_selected(0)
            assert window._clip_tag == ""
            rows = _clip_rows(window)
            assert _clip_marks(window) == [
                "Pinned",
                "c-33333333",
                "|",
                "Unpinned",
                "c-11111111",
                "c-22222222",
                "c-44444444",
            ]
            masked = next(row for row in rows if row.clip_masked)
            plain = next(row for row in rows if row.clip_text == "alpha line")
            order = [
                "document-edit-symbolic",
                "view-pin-symbolic",
                "tetherbot-tag-symbolic",
                "edit-copy-symbolic",
                "system-search-symbolic",
                "tetherbot-check-symbolic",
                "tetherbot-square-check-symbolic",
                "tetherbot-circle-help-symbolic",
                "edit-delete-symbolic",
            ]
            assert [button.get_icon_name() for button in _icon_buttons(plain)] == order
            assert [button.get_icon_name() for button in _icon_buttons(masked)] == order
            assert _icon(masked, "view-pin-symbolic").get_sensitive()
            assert "tether-pin-on" not in _icon(masked, "view-pin-symbolic").get_css_classes()
            assert "tether-pin-on" not in _icon(plain, "view-pin-symbolic").get_css_classes()
            assert _icon(masked, "view-pin-symbolic").get_tooltip_text() == "Unpin"
            assert _icon(plain, "view-pin-symbolic").get_tooltip_text() == "Pin"
            assert not _icon(masked, "tetherbot-tag-symbolic").get_sensitive()
            assert not _icon(masked, "document-edit-symbolic").get_sensitive()
            assert not _icon(masked, "system-search-symbolic").get_sensitive()
            assert _icon(masked, "edit-copy-symbolic").get_sensitive()
            assert _icon(masked, "edit-delete-symbolic").get_sensitive()
            assert _icon(plain, "tetherbot-tag-symbolic").get_sensitive()
            assert _icon(plain, "document-edit-symbolic").get_sensitive()
            assert _icon(plain, "system-search-symbolic").get_sensitive()
            assert _icon(plain, "tetherbot-check-symbolic").get_sensitive()
            assert _icon(plain, "tetherbot-square-check-symbolic").get_sensitive()
            assert _icon(plain, "tetherbot-circle-help-symbolic").get_sensitive()
            assert _icon(plain, "tetherbot-check-symbolic").get_tooltip_text() == "Make a todo"
            assert _icon(plain, "tetherbot-square-check-symbolic").get_tooltip_text() == (
                "Make a todo with context"
            )
            assert _icon(plain, "tetherbot-circle-help-symbolic").get_tooltip_text() == (
                "Tell me more"
            )
            for name in (
                "tetherbot-check-symbolic",
                "tetherbot-square-check-symbolic",
                "tetherbot-circle-help-symbolic",
            ):
                assert not _icon(masked, name).get_sensitive()
                assert _icon(masked, name).get_tooltip_text() == "Hidden passwords are not sent"
            assert _css_count(plain, "tether-clip-sep") == 8
            assert _css_count(masked, "tether-clip-sep") == 8
            shown_label = _label_text(plain, "alpha line")
            assert shown_label is not None
            assert shown_label.get_ellipsize() == Pango.EllipsizeMode.END
            assert shown_label.get_wrap() is False
            later = _tooltip(plain, "Later")
            assert later is not None
            tips = [button.get_tooltip_text() or "" for button in _icon_buttons(masked)]
            assert all("hidden-secret" not in tip for tip in tips)
            assert _icon(masked, "tetherbot-tag-symbolic").get_tooltip_text() == (
                "Hidden passwords are not tagged"
            )
            assert _icon(masked, "system-search-symbolic").get_tooltip_text() == (
                "Hidden passwords are not searched"
            )
            image = next(row for row in rows if getattr(row, "clip_kind", "") == "image")
            shown_image = _label_text(image, "Image · PNG · 1.2 MB")
            assert shown_image is not None
            assert shown_image.get_ellipsize() == Pango.EllipsizeMode.END
            assert not _icon(image, "document-edit-symbolic").get_sensitive()
            assert not _icon(image, "system-search-symbolic").get_sensitive()
            assert _icon(image, "tetherbot-tag-symbolic").get_sensitive()
            assert _icon(image, "edit-copy-symbolic").get_sensitive()
            assert _icon(image, "view-pin-symbolic").get_sensitive()
            assert _icon(image, "edit-delete-symbolic").get_sensitive()
            for name in (
                "tetherbot-check-symbolic",
                "tetherbot-square-check-symbolic",
                "tetherbot-circle-help-symbolic",
            ):
                assert not _icon(image, name).get_sensitive()
                assert _icon(image, name).get_tooltip_text() == "Images are not sent"
            assert _css_count(image, "tether-clip-sep") == 8
            assert _icon(image, "document-edit-symbolic").get_tooltip_text() == (
                "Images are not edited"
            )
            assert _icon(image, "system-search-symbolic").get_tooltip_text() == (
                "Images are not searched"
            )
            window._clip_query = "png"
            window._fill_clipboard_rows()
            matched = _clip_rows(window)
            assert [getattr(row, "clip_kind", "") for row in matched] == ["image"]
            assert _clip_marks(window) == ["Pinned", "|", "Unpinned", "c-44444444"]
            window._clip_query = "zz-bytes"
            window._fill_clipboard_rows()
            assert _clip_rows(window) == []
            assert _clip_marks(window) == ["Pinned", "|", "Unpinned", "No matches"]
            window._clip_query = ""
            window._fill_clipboard_rows()
            image = next(
                row for row in _clip_rows(window) if getattr(row, "clip_kind", "") == "image"
            )
            window._on_edit_clip(None, image.clip_entry)
            assert getattr(window, "_clip_dialog", None) is None
            assert getattr(window, "_clip_popover", None) is None
            window._preview_clipboard(image)
            popover = window._clip_popover
            assert popover is not None
            assert _label_text(popover, "Preview") is not None
            assert _label_text(popover, "That image is not available") is not None
            popover.popdown()

            def _leave() -> bool:
                holder["ok"] = True
                app.quit()
                return False

            GLib.idle_add(_leave)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_a_stale_clipboard_load_keeps_an_image_and_routes_edit_and_tag():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    image = {
        "id": "c-aaaaaaa1",
        "kind": "image",
        "mime": "image/png",
        "size": 12,
        "at": 3,
        "pinned": False,
        "tags": [],
        "text": "",
        "path": "/tetherbot-missing/clipboard-image.png",
    }
    text = {
        "id": "c-aaaaaaa2",
        "text": "alpha line",
        "at": 2,
        "pinned": False,
        "tags": [],
    }
    other = {
        "id": "c-aaaaaaa3",
        "text": "beta line",
        "at": 1,
        "pinned": False,
        "tags": [],
    }

    class _Clip:
        def __init__(self) -> None:
            self.loads: list = []
            self.current = [image, text, other]
            self.stale = [text, other]

        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return []

        def load_clipboard(self, callback) -> None:
            self.loads.append(callback)

        def get_clipboard(self):
            return [dict(row) for row in self.current]

    class _Isolated(WindowApp):
        def __init__(self, client: _Clip) -> None:
            Adw.Application.__init__(
                self,
                application_id="io.github.grokkinggrok.TetherBot.ClipGenTest",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self.window = None
            self._linger = 0

    fake = _Clip()
    app = _Isolated(fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            assert fake.loads
            fake.loads[-1](list(fake.current), None)
            assert any(row.get("kind") == "image" for row in window._clip_entries)
            window._reload_clipboard()
            stale = fake.loads[-1]
            window._reload_clip_now()
            assert any(row.get("kind") == "image" for row in window._clip_entries)
            stale(list(fake.stale), None)
            assert [row.get("id") for row in window._clip_entries] == [
                "c-aaaaaaa1",
                "c-aaaaaaa2",
                "c-aaaaaaa3",
            ]
            opened: list[tuple[str, str]] = []
            window._on_edit_clip = lambda _button, entry: opened.append(
                ("clip-edit", entry.get("id"))
            )
            window._on_tag_clip = lambda _button, entry: opened.append(
                ("clip-tag", entry.get("id"))
            )
            window.select_key("clip-edit:c-aaaaaaa2")
            window.select_key("clip-tag:c-aaaaaaa1")
            window.select_key("clip-edit:c-aaaaaaa1")
            assert opened == [
                ("clip-edit", "c-aaaaaaa2"),
                ("clip-tag", "c-aaaaaaa1"),
            ]
            assert window.banner.get_title() != "That clip is gone."
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_menu_clip_actions_open_the_page_popover():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    class _Clip:
        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return [{"name": "primary", "display_name": "Primary"}]

        def get_clipboard(self):
            return [
                {
                    "id": "c-11111111",
                    "text": "pinned line",
                    "at": 2,
                    "pinned": True,
                    "tags": [],
                },
                {
                    "id": "c-22222222",
                    "text": "loose line",
                    "at": 1,
                    "pinned": False,
                    "tags": [],
                },
            ]

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.MenuClipTest",
        _Clip(),
    )
    holder: dict = {}

    def _open(window, key: str, ident: str) -> None:
        window.select_key(key)
        assert window.get_visible()
        assert window._page == "clipboard"
        deadline = time.monotonic() + 1
        ctx = GLib.MainContext.default()
        while time.monotonic() < deadline:
            row = window._clip_row(ident)
            popover = window._clip_popover
            if (
                row is not None
                and "tether-clip-target" in row.get_css_classes()
                and popover is not None
                and popover.get_visible()
            ):
                return
            ctx.iteration(False)
        row = window._clip_row(ident)
        assert row is not None
        assert "tether-clip-target" in row.get_css_classes()
        popover = window._clip_popover
        assert popover is not None
        assert popover.get_visible()

    def _when_clear(window, step) -> None:
        def _poll(left: int) -> bool:
            if window._clip_busy() and left > 0:
                GLib.timeout_add(30, _poll, left - 1)
                return False
            step()
            return False

        GLib.timeout_add(30, _poll, 20)

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            _open(window, "clip-tag:c-11111111", "c-11111111")
            window._clip_popover.popdown()

            def _edit() -> None:
                try:
                    _open(window, "clip-edit:c-22222222", "c-22222222")
                    window._clip_popover.popdown()

                    def _context() -> None:
                        try:
                            _open(window, "clip-context:c-22222222", "c-22222222")
                            window._clip_popover.popdown()

                            def _gone() -> None:
                                try:
                                    window.select_key("clip-tag:c-99999999")
                                    assert window._page == "clipboard"
                                    assert window.banner.get_title() == "That clip is gone."
                                    assert window.banner.get_revealed()
                                    assert window._clip_popover is None
                                    _pump_quit(app, holder, GLib)
                                except Exception as exc:
                                    holder["error"] = exc
                                    app.quit()

                            _when_clear(window, _gone)
                        except Exception as exc:
                            holder["error"] = exc
                            app.quit()

                    _when_clear(window, _context)
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()

            _when_clear(window, _edit)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_context_send_opens_a_bot_picker():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    class _Clip:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str, str]] = []

        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return [
                {
                    "key": "notes/one",
                    "kind": "todo",
                    "title": "From notes",
                    "status": "open",
                    "source": {"bot": "notes"},
                }
            ]

        def get_tags(self):
            return []

        def bots(self):
            return [
                {"name": "primary", "display_name": "Primary"},
                {"name": "notes", "display_name": "Notes"},
            ]

        def get_clipboard(self):
            return [
                {
                    "id": "c-11111111",
                    "text": "alpha line",
                    "at": 2,
                    "pinned": False,
                    "tags": [],
                }
            ]

        def send_clipboard(self, entry_id: str, action: str, target_bot: str = "primary") -> str:
            self.sent.append((entry_id, action, target_bot))
            return "sent"

    class _Isolated(WindowApp):
        def __init__(self, client: _Clip) -> None:
            Adw.Application.__init__(
                self,
                application_id="io.github.grokkinggrok.TetherBot.ContextPickerTest",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self.window = None
            self._linger = 0

    client = _Clip()
    app = _Isolated(client)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            window._context_effort = lambda: "high"
            window._items = [
                {
                    "key": "notes/one",
                    "source": {"bot": "notes"},
                }
            ]
            plain = _clip_rows(window)[0]
            opens = {"n": 0}
            original = window._prompt_clip_context

            def wrapped(parent, entry, label) -> None:
                opens["n"] += 1
                original(parent, entry, label)

            window._prompt_clip_context = wrapped
            _icon(plain, "tetherbot-square-check-symbolic").emit("clicked")
            assert opens["n"] == 1
            dialog = window._clip_context_dialog
            assert dialog is not None
            assert _label_text(dialog, "Make a todo with context") is not None
            level = dialog.effort_level
            assert level.get_label() == "High"
            assert "tether-effort-high" in level.get_css_classes()
            buttons = {button.get_label(): button for button in dialog.bot_buttons}
            assert list(buttons)[:1] == ["primary"]
            assert "notes" in buttons
            assert buttons["primary"].get_active()
            dialog.cancel_button.emit("clicked")
            assert client.sent == []
            _icon(plain, "tetherbot-square-check-symbolic").emit("clicked")
            assert opens["n"] == 2
            dialog = window._clip_context_dialog
            buttons = {button.get_label(): button for button in dialog.bot_buttons}
            buttons["notes"].set_active(True)
            assert buttons["notes"].get_active()
            assert not buttons["primary"].get_active()
            dialog.send_button.emit("clicked")
            assert client.sent == [("c-11111111", "clip-todo-context", "notes")]
            shown = _label_text(plain, "Sent")
            assert shown is not None
            _icon(plain, "tetherbot-check-symbolic").emit("clicked")
            assert opens["n"] == 2
            assert client.sent[-1] == ("c-11111111", "clip-todo", "primary")
            if dialog.get_parent() is not None:
                dialog.popdown()

            def _leave() -> bool:
                holder["ok"] = True
                app.quit()
                return False

            GLib.idle_add(_leave)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _tag_clip_client():
    class _Clip:
        def __init__(self) -> None:
            self.saved: list[tuple[str, list]] = []

        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return []

        def get_clipboard(self):
            return [
                {
                    "id": "c-11111111",
                    "text": "alpha line",
                    "at": 1,
                    "pinned": False,
                    "tags": [],
                }
            ]

        def set_clipboard_tags(self, entry_id: str, tags: list) -> bool:
            self.saved.append((entry_id, tags))
            return True

    return _Clip()


def _isolated_window(app_id: str, client, drafts_path=None):
    from gi.repository import Adw, Gio

    from tetherbot.window import WindowApp

    class _Isolated(WindowApp):
        def __init__(self) -> None:
            Adw.Application.__init__(
                self,
                application_id=app_id,
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self._drafts_path = drafts_path
            self.window = None
            self._linger = 0

    return _Isolated()


def _pump_quit(app, holder, glib, steps: int = 4):
    def _pump(left: int) -> bool:
        if left > 0:
            glib.idle_add(_pump, left - 1)
            return False
        holder["ok"] = True
        app.quit()
        return False

    glib.idle_add(_pump, steps)


def _walk_widgets(widget):
    stack = [widget]
    found = []
    while stack:
        current = stack.pop()
        if current is None:
            continue
        found.append(current)
        child = current.get_first_child() if hasattr(current, "get_first_child") else None
        while child is not None:
            stack.append(child)
            nxt = child.get_next_sibling() if hasattr(child, "get_next_sibling") else None
            child = nxt
    return found


def _open_popovers(window, gtk) -> list:
    found = []
    for widget in _walk_widgets(window):
        if not isinstance(widget, gtk.Popover):
            continue
        try:
            visible = bool(widget.get_visible())
        except Exception:
            continue
        if visible:
            found.append(widget)
    return found


def _popover_title(popover) -> str:
    box = popover.get_child()
    label = box.get_first_child() if box is not None else None
    if label is not None and hasattr(label, "get_label"):
        text = label.get_label()
        if isinstance(text, str):
            return text
    return ""


def _after_responsive(glib, action, done, failed, limit: float = 0.5) -> None:
    """Run action, then call done once an idle fires inside limit seconds."""

    start = time.monotonic()
    saw = {"idle": False}

    def mark() -> bool:
        saw["idle"] = True
        return False

    action()
    glib.idle_add(mark)

    def poll() -> bool:
        if saw["idle"]:
            if time.monotonic() - start > limit:
                failed("idle tick was late")
                return False
            done()
            return False
        if time.monotonic() - start > limit:
            failed("main loop stayed busy")
            return False
        glib.timeout_add(20, poll)
        return False

    glib.timeout_add(20, poll)


def test_clip_menu_actions_keep_the_main_loop_responsive():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipLoopTest",
        _tag_clip_client(),
    )
    holder: dict = {}
    keys = (
        "clip-tag:c-11111111",
        "clip-tag:c-11111111",
        "clip-edit:c-11111111",
    )

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")

            def failed(message: str) -> None:
                holder["error"] = AssertionError(message)
                app.quit()

            def step(index: int) -> bool:
                if index >= len(keys):
                    window._close_clip_popover()

                    def _clear(left: int) -> bool:
                        if window._clip_busy() and left > 0:
                            GLib.timeout_add(30, _clear, left - 1)
                            return False
                        _pump_quit(app, holder, GLib)
                        return False

                    GLib.timeout_add(30, _clear, 20)
                    return False

                def again() -> None:
                    GLib.idle_add(step, index + 1)

                _after_responsive(
                    GLib,
                    lambda: window.select_key(keys[index]),
                    again,
                    failed,
                )
                return False

            GLib.idle_add(step, 0)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_a_burst_of_clip_actions_leaves_the_edit_popover():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipBurstTest",
        _tag_clip_client(),
    )
    holder: dict = {}
    keys = ("clip-tag:c-11111111",) * 5 + ("clip-edit:c-11111111",)

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            same = window
            window._set_page("clipboard")

            def failed(message: str) -> None:
                holder["error"] = AssertionError(message)
                app.quit()

            def settle(spins: int) -> bool:
                try:
                    titles = [_popover_title(pop) for pop in _open_popovers(window, Gtk)]
                    if titles == ["Edit"]:
                        assert app.window is same

                        def done() -> None:
                            window._close_clip_popover()

                            def _clear(left: int) -> bool:
                                if window._clip_busy() and left > 0:
                                    GLib.timeout_add(30, _clear, left - 1)
                                    return False
                                _pump_quit(app, holder, GLib)
                                return False

                            GLib.timeout_add(30, _clear, 20)

                        _after_responsive(GLib, lambda: None, done, failed)
                        return False
                    if spins > 40:
                        failed(f"popovers ended as {titles}")
                        return False
                    GLib.timeout_add(50, settle, spins + 1)
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()
                return False

            def send(index: int) -> bool:
                if index >= len(keys):
                    GLib.timeout_add(30, settle, 0)
                    return False

                def next_send() -> None:
                    GLib.timeout_add(100, send, index + 1)

                _after_responsive(
                    GLib,
                    lambda: window.select_key(keys[index]),
                    next_send,
                    failed,
                )
                return False

            GLib.idle_add(send, 0)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(15000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _two_text_clips():
    class _Clip:
        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            return None

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return []

        def get_clipboard(self):
            return [
                {
                    "id": "c-11111111",
                    "text": "alpha line",
                    "at": 2,
                    "pinned": False,
                    "tags": [],
                },
                {
                    "id": "c-22222222",
                    "text": "beta line",
                    "at": 1,
                    "pinned": False,
                    "tags": [],
                },
            ]

    return _Clip()


def _capture_clip_log():
    logger = logging.getLogger("tetherbot")
    logger.setLevel(logging.INFO)
    lines: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    handler = _Handler()
    logger.addHandler(handler)
    return lines


def _capture_gtk_warnings():
    from gi.repository import GLib

    found: list[str] = []

    def handler(*args) -> None:
        message = args[2] if len(args) > 2 else ""
        found.append(str(message))

    flags = GLib.LogLevelFlags.LEVEL_WARNING | GLib.LogLevelFlags.LEVEL_CRITICAL
    watches = []
    for domain in ("Gtk", "GLib-GObject"):
        try:
            watch = GLib.log_set_handler(domain, flags, handler)
        except TypeError:
            watch = GLib.log_set_handler(domain, flags, handler, None)
        watches.append((domain, watch))
    return found, watches


def _drop_gtk_warnings(watches) -> None:
    from gi.repository import GLib

    for domain, watch in watches:
        try:
            GLib.log_remove_handler(domain, watch)
        except Exception:
            continue


def _poll(glib, pred, done, failed, left: int = 40) -> None:
    """Call done when pred is true. Poll on the running main loop."""

    def tick(remaining: int) -> bool:
        try:
            if pred():
                done()
                return False
            if remaining <= 0:
                failed("timed out")
                return False
        except Exception as exc:
            failed(exc)
            return False
        glib.timeout_add(30, tick, remaining - 1)
        return False

    glib.timeout_add(30, tick, left)


def test_an_unready_clip_button_retries_until_the_popover_opens():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipReadyRetry",
        _two_text_clips(),
    )
    holder: dict = {}
    lines = _capture_clip_log()

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")

            def failed(message) -> None:
                if isinstance(message, Exception):
                    holder["error"] = message
                else:
                    holder["error"] = AssertionError(str(message))
                app.quit()

            def opened() -> None:
                assert any(line.startswith("clip popup gen=") for line in lines)
                assert not any("clip popup skipped" in line for line in lines)
                window._close_clip_popover()
                _pump_quit(app, holder, GLib)

            def start() -> None:
                original = window._mount_clip_popover
                state = {"n": 0, "button": None}

                def wrapped(parent, child):
                    state["n"] += 1
                    if state["n"] == 1:
                        state["button"] = parent
                        parent.set_visible(False)
                    return original(parent, child)

                window._mount_clip_popover = wrapped
                window.select_key("clip-edit:c-11111111")
                assert window._clip_pending == ("clip-edit", "c-11111111")
                assert any("clip popup wait" in line for line in lines)
                assert not any("clip popup skipped" in line for line in lines)
                assert state["button"] is not None
                state["button"].set_visible(True)
                _poll(
                    GLib,
                    lambda: (
                        window._clip_popover is not None
                        and window._clip_popover.get_visible()
                        and window._clip_pending is None
                    ),
                    opened,
                    failed,
                    left=60,
                )

            _poll(
                GLib,
                lambda: window._clip_popup_block("clip-edit", "c-11111111")[0] == "",
                start,
                failed,
            )
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_an_unready_clip_button_gives_up_after_the_deadline():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import _CLIP_ACTION_WAIT_S

    assert _CLIP_ACTION_WAIT_S == 2.0
    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipReadyGiveUp",
        _two_text_clips(),
    )
    holder: dict = {}
    lines = _capture_clip_log()

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            found = {}

            def failed(message) -> None:
                if isinstance(message, Exception):
                    holder["error"] = message
                else:
                    holder["error"] = AssertionError(str(message))
                app.quit()

            def ready() -> bool:
                fail, button, _row = window._clip_popup_block("clip-edit", "c-11111111")
                if fail == "" and button is not None:
                    found["button"] = button
                    return True
                return False

            def gave_up() -> None:
                assert any("clip popup gave up" in line for line in lines)
                assert any("clip popup wait" in line for line in lines)
                assert not any("clip popup skipped" in line for line in lines)
                _pump_quit(app, holder, GLib)

            def hide_and_request() -> None:
                found["button"].set_visible(False)
                window.select_key("clip-edit:c-11111111")
                window._clip_action_deadline = time.monotonic() - 1
                _poll(
                    GLib,
                    lambda: (
                        window._clip_pending is None
                        and window.banner.get_revealed()
                        and window.banner.get_title() == "Couldn't open that clip."
                    ),
                    gave_up,
                    failed,
                )

            _poll(GLib, ready, hide_and_request, failed)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_a_clipboard_rebuild_unparents_open_and_closing_popovers():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipDetach",
        _two_text_clips(),
    )
    holder: dict = {}
    lines = _capture_clip_log()
    warnings, watches = _capture_gtk_warnings()

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")

            def failed(message) -> None:
                if isinstance(message, Exception):
                    holder["error"] = message
                else:
                    holder["error"] = AssertionError(str(message))
                app.quit()

            def closing() -> None:
                row = window._clip_row("c-11111111")
                _icon(row, "tetherbot-tag-symbolic").emit("clicked")
                popover = window._clip_popover
                assert popover is not None
                popover.popdown()
                window._fill_clipboard_rows()

                def check() -> bool:
                    try:
                        assert not any(
                            "Finalizing GtkButton" in message for message in warnings
                        )
                        assert not any("clip dispose popover" in line for line in lines)
                        _pump_quit(app, holder, GLib)
                    except Exception as exc:
                        holder["error"] = exc
                        app.quit()
                    return False

                GLib.timeout_add(200, check)

            def opened() -> None:
                row = window._clip_row("c-11111111")
                _icon(row, "tetherbot-tag-symbolic").emit("clicked")
                assert window._clip_popover is not None
                assert window._clip_popover.get_visible()
                window._fill_clipboard_rows()
                assert window._clip_popover is None
                _poll(
                    GLib,
                    lambda: window._clip_popup_block("clip-tag", "c-11111111")[0] == "",
                    closing,
                    failed,
                )

            _poll(
                GLib,
                lambda: window._clip_popup_block("clip-tag", "c-11111111")[0] == "",
                opened,
                failed,
            )
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        _drop_gtk_warnings(watches)
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_edit_opens_while_a_tag_popover_is_open():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.ClipReplace",
        _two_text_clips(),
    )
    holder: dict = {}

    def _titles(window) -> list[str]:
        return [_popover_title(popover) for popover in _open_popovers(window, Gtk)]

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")

            def failed(message) -> None:
                if isinstance(message, Exception):
                    holder["error"] = message
                else:
                    holder["error"] = AssertionError(str(message))
                app.quit()

            def open_edit_same() -> None:
                def settled() -> None:
                    assert len(_open_popovers(window, Gtk)) == 1
                    window._close_clip_popover()
                    _pump_quit(app, holder, GLib)

                _poll(GLib, lambda: _titles(window) == ["Edit"], settled, failed, left=70)

            def open_tag_same() -> None:
                def again() -> None:
                    _after_responsive(
                        GLib,
                        lambda: window.select_key("clip-edit:c-11111111"),
                        open_edit_same,
                        failed,
                    )

                _poll(GLib, lambda: _titles(window) == ["New tag"], again, failed, left=70)

            def open_edit_other() -> None:
                def again() -> None:
                    assert len(_open_popovers(window, Gtk)) == 1
                    _after_responsive(
                        GLib,
                        lambda: window.select_key("clip-tag:c-11111111"),
                        open_tag_same,
                        failed,
                    )

                _poll(GLib, lambda: _titles(window) == ["Edit"], again, failed, left=70)

            def open_tag() -> None:
                def again() -> None:
                    _after_responsive(
                        GLib,
                        lambda: window.select_key("clip-edit:c-22222222"),
                        open_edit_other,
                        failed,
                    )

                _poll(GLib, lambda: _titles(window) == ["New tag"], again, failed, left=70)

            _after_responsive(
                GLib,
                lambda: window.select_key("clip-tag:c-11111111"),
                open_tag,
                failed,
            )
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(15000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _direct_labels(widget) -> list[str]:
    labels: list[str] = []
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        text = child.get_label() if hasattr(child, "get_label") else None
        if isinstance(text, str) and text:
            labels.append(text)
        child = child.get_next_sibling()
    return labels


def test_tag_editor_layout_and_save_keeps_typed_text():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gdk, GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    client = _tag_clip_client()
    app = _isolated_window("io.github.grokkinggrok.TetherBot.TagLayoutTest", client)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            plain = _clip_rows(window)[0]
            _icon(plain, "tetherbot-tag-symbolic").emit("clicked")

            def check() -> bool:
                try:
                    popover = window._clip_popover
                    assert popover is not None
                    box = popover.get_child()
                    labels = _direct_labels(box)
                    assert labels[:1] == ["New tag"]
                    assert "Applied tags" in labels
                    assert labels.index("New tag") < labels.index("Applied tags")
                    entry = box.tag_entry
                    entry_row = entry.get_parent()
                    assert _find_button(entry_row, "Add") is not None
                    none = _find_button(box, "None yet")
                    assert none is not None
                    assert none.get_visible()
                    assert "dim-label" in none.get_css_classes()
                    focus = window.get_focus()
                    assert focus is not None
                    assert focus is entry or focus.is_ancestor(entry)
                    assert window._on_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0)) is False
                    entry.set_text("Later")
                    entry.emit("activate")
                    assert entry.get_text() == ""
                    assert not none.get_visible()
                    assert _label_text(box, "Later") is not None
                    entry.set_text("  Soon  ")
                    add = _find_button(entry_row, "Add")
                    assert add is not None
                    add.emit("clicked")
                    assert _label_text(box, "Soon") is not None
                    entry.set_text("Skip")
                    cancel = _find_button(box, "Cancel")
                    assert cancel is not None
                    cancel.emit("clicked")

                    def canceled() -> bool:
                        try:
                            assert window._clip_popover is None
                            assert client.saved == []
                            row = _clip_rows(window)[0]
                            _icon(row, "tetherbot-tag-symbolic").emit("clicked")
                            again = window._clip_popover
                            assert again is not None
                            again.get_child().tag_entry.set_text("  Kept  ")
                            save = _find_button(again, "Save")
                            assert save is not None
                            save.emit("clicked")
                            assert client.saved == [
                                ("c-11111111", [{"name": "Kept", "color": "red"}])
                            ]

                            def closed() -> bool:
                                try:
                                    assert window._clip_popover is None
                                    assert window.get_visible()
                                    assert _clip_rows(window)
                                    _pump_quit(app, holder, GLib)
                                except Exception as exc:
                                    holder["error"] = exc
                                    app.quit()
                                return False

                            GLib.idle_add(closed)
                        except Exception as exc:
                            holder["error"] = exc
                            app.quit()
                        return False

                    GLib.idle_add(canceled)
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()
                return False

            GLib.idle_add(check)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_tag_popover_stays_open_when_the_pointer_leaves():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    client = _tag_clip_client()
    app = _isolated_window("io.github.grokkinggrok.TetherBot.TagPointerTest", client)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            plain = _clip_rows(window)[0]
            _icon(plain, "tetherbot-tag-symbolic").emit("clicked")
            popover = window._clip_popover
            assert popover is not None
            entry = popover.get_child().tag_entry
            seen = {"enter": 0, "leave": 0}
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda *_args: seen.__setitem__("enter", seen["enter"] + 1))
            motion.connect("leave", lambda *_args: seen.__setitem__("leave", seen["leave"] + 1))
            entry.add_controller(motion)
            motion.emit("enter", 2.0, 3.0)
            motion.emit("leave")
            assert seen == {"enter": 1, "leave": 1}
            entry.remove_controller(motion)
            assert window._clip_popover is popover
            assert popover.get_visible()
            entry.set_text("  Later  ")
            save = _find_button(popover, "Save")
            assert save is not None
            save.emit("clicked")
            assert client.saved == [("c-11111111", [{"name": "Later", "color": "red"}])]

            def check() -> bool:
                try:
                    assert window._clip_popover is None
                    assert window.get_visible()
                    assert _clip_rows(window)
                    _pump_quit(app, holder, GLib)
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()
                return False

            GLib.idle_add(check)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_minus_one_minute_sits_left_of_minus_five():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    fake = _EditFake()
    fake.timer = {
        "state": "running",
        "item_key": "",
        "item_title": "",
        "elapsed_s": 5 * 60,
    }
    app = _isolated_window("io.github.grokkinggrok.TetherBot.MinusOneTest", fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            window._request_timer()
            edit = _find_button(window.timer_actions, "Edit start")
            assert edit is not None
            edit.emit("clicked")
            assert window.edit_start_box.get_visible()
            labels = _direct_labels(window.edit_start_box)
            assert labels.index("-1m") < labels.index("-5m")
            minus = _find_button(window.edit_start_box, "-1m")
            assert minus is not None
            minus.emit("clicked")
            assert fake.adjusted == [-60]
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def _clip_rows(window) -> list:
    rows = []
    index = 0
    while True:
        row = window.list.get_row_at_index(index)
        if row is None:
            return rows
        if getattr(row, "clip_id", ""):
            rows.append(row)
        index += 1


def _clip_marks(window) -> list:
    marks = []
    index = 0
    while True:
        row = window.list.get_row_at_index(index)
        if row is None:
            return marks
        heading = getattr(row, "clip_heading", "")
        if heading:
            marks.append(heading)
        elif getattr(row, "clip_separator", False):
            marks.append("|")
        elif getattr(row, "clip_note", ""):
            marks.append(row.clip_note)
        elif getattr(row, "clip_id", ""):
            marks.append(row.clip_id)
        index += 1


def _icon_buttons(widget):
    found = []
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        classes = child.get_css_classes() if hasattr(child, "get_css_classes") else []
        if "tether-clip-action" in classes:
            found.append(child)
        found.extend(_icon_buttons(child))
        child = child.get_next_sibling()
    return found


def _icon(widget, name: str):
    match = next(
        (button for button in _icon_buttons(widget) if button.get_icon_name() == name),
        None,
    )
    assert match is not None, name
    return match


def _pinned_clip_client():
    class _Clip:
        def __init__(self) -> None:
            self.entries = [
                {
                    "id": "c-11111111",
                    "text": "pinned line",
                    "at": 1,
                    "pinned": True,
                    "tags": [],
                }
            ]
            self.listener = None
            self.edits: list[tuple[str, str]] = []
            self.saved: list[tuple[str, list]] = []

        def set_listener(self, listener) -> None:
            return None

        def set_clipboard_listener(self, listener) -> None:
            self.listener = listener

        def get_items(self, spec):
            return []

        def get_tags(self):
            return []

        def bots(self):
            return []

        def get_clipboard(self):
            return [dict(entry) for entry in self.entries]

        def _notify(self) -> None:
            listener = self.listener
            if listener is not None:
                listener()

        def edit_clipboard(self, entry_id: str, text: str) -> bool:
            self.edits.append((entry_id, text))
            for entry in self.entries:
                if entry.get("id") == entry_id:
                    entry["text"] = text
            self._notify()
            return True

        def set_clipboard_tags(self, entry_id: str, tags: list) -> bool:
            self.saved.append((entry_id, [dict(tag) for tag in tags]))
            for entry in self.entries:
                if entry.get("id") == entry_id:
                    entry["tags"] = [dict(tag) for tag in tags]
            self._notify()
            return True

    return _Clip()


def _visible_clip_row(window, entry_id: str):
    found = None
    for row in _clip_rows(window):
        if getattr(row, "clip_id", "") == entry_id and row.get_visible():
            found = row
    assert found is not None, entry_id
    return found


def _editor_settled(window) -> bool:
    return (
        window._clip_popover is None
        and window._closed_popover is None
        and not window._clip_close_queued
        and not window._clip_popover_closing
        and not window._clip_close_source
        and not window._clip_drop_source
        and not window._clip_rebuild_deferred
    )


def _run_pinned_script(app_id: str, client, actions: list, timeout_ms: int) -> None:
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    app = _isolated_window(app_id, client)
    holder: dict = {}

    def finish() -> bool:
        try:
            window = app.window
            assert window is not None
            window._set_page("clipboard")
            state = {"index": 0, "spins": 0, "phase": "act"}

            def tick() -> bool:
                try:
                    if state["phase"] == "wait":
                        if not _editor_settled(window):
                            state["spins"] += 1
                            if state["spins"] > 50:
                                raise AssertionError("clip editor stayed open")
                            GLib.idle_add(tick)
                            return False
                        state["phase"] = "act"
                        state["spins"] = 0
                    if state["index"] >= len(actions):
                        assert window.get_visible()
                        _visible_clip_row(window, "c-11111111")
                        _pump_quit(app, holder, GLib, steps=6)
                        return False
                    actions[state["index"]](window)
                    state["index"] += 1
                    state["phase"] = "wait"
                    state["spins"] = 0
                    GLib.idle_add(tick)
                except Exception as exc:
                    holder["error"] = exc
                    app.quit()
                return False

            GLib.idle_add(tick)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(timeout_ms, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_first_pinned_edit_closes_without_crashing():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
    except ValueError as exc:
        pytest.skip(str(exc))

    client = _pinned_clip_client()

    def save(window) -> None:
        row = _visible_clip_row(window, "c-11111111")
        _icon(row, "document-edit-symbolic").emit("clicked")
        popover = window._clip_popover
        assert popover is not None
        button = _find_button(popover, "Save")
        assert button is not None
        button.emit("clicked")

    def cancel(window) -> None:
        row = _visible_clip_row(window, "c-11111111")
        _icon(row, "document-edit-symbolic").emit("clicked")
        popover = window._clip_popover
        assert popover is not None
        button = _find_button(popover, "Cancel")
        assert button is not None
        before = len(client.edits)
        button.emit("clicked")
        assert len(client.edits) == before

    def escape(window) -> None:
        row = _visible_clip_row(window, "c-11111111")
        _icon(row, "document-edit-symbolic").emit("clicked")
        assert window._clip_popover is not None
        before = len(client.edits)
        window._on_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
        assert len(client.edits) == before

    _run_pinned_script(
        "io.github.grokkinggrok.TetherBot.PinnedEditTest",
        client,
        [save, cancel, escape],
        20000,
    )
    assert len(client.edits) == 1
    assert client.edits[0][0] == "c-11111111"


def test_tag_and_pinned_edit_survive_a_long_run():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
    except ValueError as exc:
        pytest.skip(str(exc))

    client = _pinned_clip_client()

    def tag_once(window) -> None:
        row = _visible_clip_row(window, "c-11111111")
        _icon(row, "tetherbot-tag-symbolic").emit("clicked")
        popover = window._clip_popover
        assert popover is not None
        popover.get_child().tag_entry.set_text("Later")
        save = _find_button(popover, "Save")
        assert save is not None
        save.emit("clicked")

    def edit_once(mode: str):
        def act(window) -> None:
            row = _visible_clip_row(window, "c-11111111")
            _icon(row, "document-edit-symbolic").emit("clicked")
            popover = window._clip_popover
            assert popover is not None
            if mode == "save":
                button = _find_button(popover, "Save")
                assert button is not None
                button.emit("clicked")
                return
            if mode == "cancel":
                button = _find_button(popover, "Cancel")
                assert button is not None
                button.emit("clicked")
                return
            window._on_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))

        return act

    modes = ("save", "cancel", "escape")
    actions = [tag_once] * 50 + [edit_once(modes[index % 3]) for index in range(20)]
    _run_pinned_script(
        "io.github.grokkinggrok.TetherBot.ClipStressTest",
        client,
        actions,
        180000,
    )
    assert len(client.saved) == 50
    assert len(client.edits) == 7


def _css_count(widget, name: str) -> int:
    count = 0
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        classes = child.get_css_classes() if hasattr(child, "get_css_classes") else []
        if name in classes:
            count += 1
        count += _css_count(child, name)
        child = child.get_next_sibling()
    return count


def _label_text(widget, text: str):
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        label = child.get_label() if hasattr(child, "get_label") else None
        if label == text and hasattr(child, "get_ellipsize"):
            return child
        found = _label_text(child, text)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _tooltip(widget, text: str):
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        tip = child.get_tooltip_text() if hasattr(child, "get_tooltip_text") else None
        if tip == text:
            return child
        found = _tooltip(child, text)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _bot_labels(window) -> list[str]:
    labels = []
    index = 0
    while True:
        row = window.list.get_row_at_index(index)
        if row is None:
            return labels
        labels.append(getattr(row, "bot_label", ""))
        index += 1


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


def test_a_long_todo_title_leaves_the_start_timer_button_visible():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.window import WindowApp

    title = "Pack the bag " * 20
    tip = f"Start timer: {title.strip()}"

    class _Long(_TimerFake):
        def __init__(self) -> None:
            super().__init__()
            self.items = [
                {
                    "key": "primary/long",
                    "kind": "todo",
                    "title": title.strip(),
                    "body": "",
                    "status": "open",
                    "actions": ["done"],
                    "source": {"bot": "primary"},
                }
            ]

    class _Isolated(WindowApp):
        def __init__(self, client: _Long) -> None:
            Adw.Application.__init__(
                self,
                application_id="io.github.grokkinggrok.TetherBot.TimerRowTest",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self.window = None
            self._linger = 0

    app = _Isolated(_Long())
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            play = _find_play(window.list, tip)
            assert play is not None
            scroll = window._list_scroll
            assert scroll.get_policy()[0] == Gtk.PolicyType.NEVER
            assert scroll.get_width() > 0
            ok, bounds = play.compute_bounds(scroll)
            assert ok
            assert bounds.get_x() >= -1
            assert bounds.get_x() + bounds.get_width() <= scroll.get_width() + 1
            icon = play.get_child()
            assert icon is not None
            icon_natural = icon.measure(Gtk.Orientation.HORIZONTAL, -1).natural
            assert icon.get_width() + 1 >= icon_natural
            assert icon.get_height() + 1 >= icon.measure(Gtk.Orientation.VERTICAL, -1).natural
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_a_secret_looking_note_stays_in_the_field():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")

    from tetherbot.bridge_errors import SECRET_NOTE_MESSAGE
    from tetherbot.window import BridgeError, WindowApp

    phrase = "ghp_notarealtoken"
    raw = (
        "GDBus.Error:io.github.grokkinggrok.TetherBot1.Error.InvalidArgs: "
        "refusing to queue an action that looks like a secret"
    )

    class _Notes(_Fake):
        pass

    class _Isolated(WindowApp):
        def __init__(self, client: _Notes) -> None:
            Adw.Application.__init__(
                self,
                application_id="io.github.grokkinggrok.TetherBot.SecretNoteTest",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self._client = client
            self.window = None
            self._linger = 0

    fake = _Notes()
    app = _Isolated(fake)
    holder: dict = {}

    def finish():
        try:
            window = app.window
            assert window is not None
            toasts: list[str] = []
            window._toast = lambda message: toasts.append(message)
            window.select_key("primary/one")
            window.note_buffer.set_text(phrase)
            window._done_with_note()
            assert toasts == [SECRET_NOTE_MESSAGE]
            assert phrase not in toasts[0]
            assert "GDBus" not in toasts[0]
            assert window._note_text() == phrase
            assert "primary/one" not in window._undo_holds
            assert fake.done == []
            window.note_buffer.set_text("Packed the blue bag")
            window._done_with_note()
            assert window._note_text() == ""
            assert "primary/one" in window._undo_holds
            window._undo_holds["primary/one"]["until"] = 0

            def refuse(key, note=""):
                fake.done.append(key)
                fake.done_notes.append(note)
                raise BridgeError(f"{raw} {phrase}")

            fake.mark_done = refuse
            window._flush_due(False)
            assert toasts[-1] == SECRET_NOTE_MESSAGE
            assert phrase not in toasts[-1]
            assert "Packed" not in toasts[-1]
            assert "GDBus" not in toasts[-1]
            assert "primary/one" not in window._undo_holds
            window._show_item(fake.get_item("primary/one"))
            assert window._note_text() == "Packed the blue bag"
            holder["ok"] = True
        except Exception as exc:
            holder["error"] = exc
        app.quit()
        return False

    try:
        app.connect("activate", lambda _app: GLib.idle_add(finish))
        GLib.timeout_add(8000, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True

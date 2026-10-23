# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke the TetherBot window against a fake bridge client."""

import os

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
    # One line at the default and minimum window widths. A narrow measure wraps.
    assert 24 <= window.action_row.get_height() <= 48
    wide = window.action_row.measure(gtk.Orientation.VERTICAL, 4000).natural
    narrow = window.action_row.measure(gtk.Orientation.VERTICAL, 320).natural
    assert narrow > wide
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
        from gi.repository import GLib
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
            ]

    app = WindowApp(client=_Clip())
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
                if fills["n"] > 3:
                    raise AssertionError("tag filter rebuilt without stopping")
                original()

            window._fill_clipboard_rows = wrapped
            window.clip_tag.set_selected(1)
            assert fills["n"] == 1
            assert window._clip_tag == "Later"
            shown = _clip_rows(window)
            assert [row.clip_text for row in shown] == ["alpha line"]
            window.clip_tag.set_selected(0)
            assert window._clip_tag == ""
            rows = _clip_rows(window)
            masked = next(row for row in rows if row.clip_masked)
            plain = next(row for row in rows if row.clip_text == "alpha line")
            assert _button(masked, "Unpin").get_sensitive()
            assert not _button(masked, "Tag").get_sensitive()
            assert not _button(masked, "Edit").get_sensitive()
            assert not _button(masked, "Search the web").get_sensitive()
            assert _button(plain, "Tag").get_sensitive()
            assert _button(plain, "Search the web").get_sensitive()
            labels = [button.get_label() or "" for button in _buttons(masked)]
            assert all("hidden-secret" not in label for label in labels)
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


def _buttons(widget):
    found = []
    child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    while child is not None:
        if hasattr(child, "get_label") and child.get_label():
            found.append(child)
        found.extend(_buttons(child))
        child = child.get_next_sibling()
    return found


def _button(widget, label: str):
    match = next((button for button in _buttons(widget) if button.get_label() == label), None)
    assert match is not None, label
    return match


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

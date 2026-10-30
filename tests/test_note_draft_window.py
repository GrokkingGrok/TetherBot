# SPDX-License-Identifier: GPL-2.0-or-later
"""Note drafts in the window. These tests use an isolated app id."""

import os
import stat
import time

import pytest

from tests.helpers import reset_tetherbot_logger
from tests.test_window_ui import _Fake, _isolated_window, _poll


class _DraftFake(_Fake):
    def __init__(self) -> None:
        super().__init__()
        self.items = [
            _todo("primary/one", "Pack the bag"),
            _todo("primary/two", "Water the plant"),
        ]
        self.offline = False
        self.filtered = False

    def get_items(self, spec):
        self.specs.append(spec)
        items = list(self.items)
        if self.filtered:
            items = [item for item in items if item.get("key") != "primary/one"]
        return items

    def mark_done(self, key, note=""):
        self.done.append(key)
        self.done_notes.append(note)
        if self.offline:
            from tetherbot.window import BridgeError

            raise BridgeError("Bridge not running")
        return "a-done"


def _todo(key: str, title: str) -> dict:
    return {
        "key": key,
        "kind": "todo",
        "title": title,
        "body": "",
        "status": "open",
        "actions": ["done"],
        "source": {"bot": "primary"},
    }


def _glib():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import GLib
    except ValueError as exc:
        pytest.skip(str(exc))
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("GTK window test needs a display")
    return GLib


def _fail(app, holder, problem) -> None:
    if isinstance(problem, Exception):
        holder["error"] = problem
    else:
        holder["error"] = AssertionError(str(problem))
    app.quit()


def _launch(app, glib, start, timeout_ms: int = 8000):
    holder: dict = {}

    def finish() -> bool:
        try:
            start(app, holder)
        except Exception as exc:
            holder["error"] = exc
            app.quit()
        return False

    try:
        app.connect("activate", lambda _app: glib.idle_add(finish))
        glib.timeout_add(timeout_ms, app.quit)
        app.run(["tetherbot-window"])
    finally:
        reset_tetherbot_logger()
    if "error" in holder:
        raise holder["error"]
    assert holder.get("ok") is True


def test_a_note_draft_is_saved_on_blur_debounce_and_switch(tmp_path):
    glib = _glib()
    path = tmp_path / "note-drafts.json"
    fake = _DraftFake()
    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.NoteDraftBlurTest",
        fake,
        drafts_path=path,
    )
    phrase = "ghp_notarealtoken"

    def start(application, holder) -> None:
        window = application.window
        assert window is not None
        window.select_key("primary/one")

        def began() -> None:
            started = time.monotonic()
            window.note_buffer.set_text("bring the charger")
            assert "primary/one" not in window._note_drafts

            def saved() -> bool:
                return window._note_drafts.get("primary/one") == "bring the charger"

            def after_debounce() -> None:
                elapsed = time.monotonic() - started
                if elapsed < 0.4:
                    _fail(application, holder, "draft saved before the debounce")
                    return
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
                assert "bring the charger" in path.read_text(encoding="utf-8")
                window.note_view.grab_focus()
                window.note_buffer.set_text("bring the charger and cable")
                assert window._note_drafts["primary/one"] == "bring the charger"
                moved = time.monotonic()

                def blurred() -> bool:
                    text = window._note_drafts.get("primary/one")
                    return text == "bring the charger and cable"

                def after_blur() -> None:
                    if time.monotonic() - moved < 0.25:
                        holder["left_fast"] = True
                    window.note_view.grab_focus()
                    window.note_buffer.set_text("after the window rests")
                    original = window.is_active
                    window.is_active = lambda: False
                    try:
                        window._on_window_active(window, None)
                    finally:
                        window.is_active = original
                    assert window._note_drafts["primary/one"] == "after the window rests"
                    window.note_buffer.set_text("note for one")
                    window.select_key("primary/two")
                    assert window._note_drafts["primary/one"] == "note for one"
                    assert window._note_text() == ""
                    window.note_buffer.set_text("note for two")
                    window.select_key("primary/one")
                    assert window._note_text() == "note for one"
                    assert window._note_drafts["primary/two"] == "note for two"
                    window.note_buffer.set_text("   ")
                    window._commit_current_note_draft()
                    assert "primary/one" not in window._note_drafts
                    assert window._note_drafts["primary/two"] == "note for two"
                    window.note_buffer.set_text(phrase)
                    window._commit_current_note_draft()
                    raw = path.read_text(encoding="utf-8")
                    assert phrase not in raw
                    assert window._note_secret_drafts["primary/one"] == phrase
                    assert "primary/one" not in window._note_drafts
                    assert "note for two" in raw
                    window.note_buffer.set_text("saved on close")
                    window._on_window_close(window)
                    assert window._note_drafts["primary/one"] == "saved on close"
                    assert window._note_drafts["primary/two"] == "note for two"
                    assert phrase not in path.read_text(encoding="utf-8")
                    holder["ok"] = True
                    application.quit()

                _poll(
                    glib,
                    blurred,
                    after_blur,
                    lambda problem: _fail(application, holder, problem),
                )

            _poll(
                glib,
                saved,
                after_debounce,
                lambda problem: _fail(application, holder, problem),
                left=80,
            )

        _poll(
            glib,
            window.note_view.grab_focus,
            began,
            lambda problem: _fail(application, holder, problem),
        )

    _launch(app, glib, start, timeout_ms=12000)


def test_a_note_draft_survives_offline_rebuild_and_prune(tmp_path):
    glib = _glib()
    path = tmp_path / "note-drafts.json"
    fake = _DraftFake()
    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.NoteDraftOfflineTest",
        fake,
        drafts_path=path,
    )

    def start(application, holder) -> None:
        from tetherbot.window import BridgeError

        window = application.window
        assert window is not None
        window.select_key("primary/one")
        window.note_buffer.set_text("stay with one")
        window._commit_current_note_draft()
        window.select_key("primary/two")
        window._done_current()
        fake.offline = True
        window._undo_holds["primary/two"]["until"] = 0
        window._flush_due(False)
        assert window._undo_holds["primary/two"].get("failed") is True
        assert window._note_drafts["primary/one"] == "stay with one"
        fake.offline = False
        fake.filtered = True
        window.refresh()
        window.select_key("primary/one")
        assert window._note_text() == "stay with one"
        assert window._note_drafts["primary/one"] == "stay with one"
        original = window.client.get_item

        def get_item(key):
            if key == "gone/item":
                raise BridgeError("item not found")
            if key == "down/item":
                raise BridgeError("Bridge not running")
            if key == "odd/item":
                raise AssertionError(key)
            return original(key)

        window.client.get_item = get_item
        window._note_drafts["gone/item"] = "drop me"
        window._note_drafts["down/item"] = "bridge down"
        window._note_drafts["odd/item"] = "fake miss"
        window._prune_note_drafts()
        assert "gone/item" not in window._note_drafts
        assert window._note_drafts["down/item"] == "bridge down"
        assert window._note_drafts["odd/item"] == "fake miss"
        assert window._note_drafts["primary/one"] == "stay with one"
        assert "drop me" not in path.read_text(encoding="utf-8")
        holder["ok"] = True
        application.quit()

    _launch(app, glib, start)


def test_a_note_draft_loads_in_a_new_window(tmp_path):
    glib = _glib()
    path = tmp_path / "note-drafts.json"
    first = _isolated_window(
        "io.github.grokkinggrok.TetherBot.NoteDraftRestartA",
        _DraftFake(),
        drafts_path=path,
    )

    def start_first(application, holder) -> None:
        window = application.window
        assert window is not None
        window.select_key("primary/one")
        window.note_buffer.set_text("bring the charger")
        window._on_window_close(window)
        assert window._note_drafts["primary/one"] == "bring the charger"
        holder["ok"] = True
        application.quit()

    _launch(first, glib, start_first)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    second = _isolated_window(
        "io.github.grokkinggrok.TetherBot.NoteDraftRestartB",
        _DraftFake(),
        drafts_path=path,
    )

    def start_second(application, holder) -> None:
        window = application.window
        assert window is not None
        assert window._note_drafts["primary/one"] == "bring the charger"
        window.select_key("primary/one")
        assert window._note_text() == "bring the charger"
        holder["ok"] = True
        application.quit()

    _launch(second, glib, start_second)


def test_done_with_note_clears_a_draft_only_after_accept(tmp_path):
    glib = _glib()
    path = tmp_path / "note-drafts.json"
    fake = _DraftFake()
    app = _isolated_window(
        "io.github.grokkinggrok.TetherBot.NoteDraftDoneTest",
        fake,
        drafts_path=path,
    )

    def start(application, holder) -> None:
        from tetherbot.window import BridgeError

        window = application.window
        assert window is not None
        window.select_key("primary/two")
        window.note_buffer.set_text("other todo")
        window._commit_current_note_draft()
        window.select_key("primary/one")
        window.note_buffer.set_text("note one")
        window._done_with_note()
        assert window._note_text() == ""
        assert window._note_drafts["primary/one"] == "note one"
        assert window._note_drafts["primary/two"] == "other todo"
        window._undo_holds["primary/one"]["until"] = 0
        window._flush_due(False)
        assert window._note_sends["a-done"] == ("primary/one", "note one")
        window._on_action_result("a-done", "queued_retry", "")
        assert window._note_sends["a-done"] == ("primary/one", "note one")
        assert window._note_drafts["primary/one"] == "note one"
        window.note_buffer.set_text("note one revised")
        window._commit_current_note_draft()
        window._on_action_result("a-done", "accepted", "")
        assert window._note_drafts["primary/one"] == "note one revised"
        assert window._note_text() == "note one revised"
        assert window._note_drafts["primary/two"] == "other todo"
        window._note_sends["a-park"] = ("primary/one", "note one revised")
        window._done_actions.add("a-park")
        window._on_action_result("a-park", "parked", "")
        assert "a-park" not in window._note_sends
        assert window._note_drafts["primary/one"] == "note one revised"
        window._note_sends["a-drop"] = ("primary/one", "note one revised")
        window._done_actions.add("a-drop")
        window._on_action_result("a-drop", "dropped", "")
        assert "a-drop" not in window._note_sends
        assert window._note_drafts["primary/one"] == "note one revised"
        window._note_sends["a-rej"] = ("primary/one", "note one revised")
        window._done_actions.add("a-rej")
        window._on_action_result("a-rej", "rejected_key", "")
        assert "a-rej" not in window._note_sends
        assert window._note_drafts["primary/one"] == "note one revised"
        window.note_buffer.set_text("kept after failure")
        window._done_with_note()
        assert window._note_text() == ""
        assert window._note_drafts["primary/one"] == "kept after failure"

        def refuse(key, note=""):
            fake.done.append(key)
            fake.done_notes.append(note)
            raise BridgeError("could not send")

        fake.mark_done = refuse
        window._undo_holds["primary/one"]["until"] = 0
        window._flush_due(False)
        assert window._undo_holds["primary/one"].get("failed") is True
        assert window._note_drafts["primary/one"] == "kept after failure"
        window._on_window_close(window)
        assert window._note_drafts["primary/one"] == "kept after failure"
        assert window._note_drafts["primary/two"] == "other todo"
        raw = path.read_text(encoding="utf-8")
        assert "kept after failure" in raw
        assert "other todo" in raw
        holder["ok"] = True
        application.quit()

    _launch(app, glib, start)

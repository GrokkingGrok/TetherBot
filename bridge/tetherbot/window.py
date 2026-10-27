# SPDX-License-Identifier: GPL-2.0-or-later
"""The TetherBot window.

A separate process from the bridge and from the Shell extension. It reads
and checks off todos over the session bus. It holds no secrets and makes
no network calls. Links open only after a click, through the default browser.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from tetherbot.bridge_errors import (  # noqa: E402
    SECRET_NOTE_MESSAGE,
    clip_send_message,
    friendly_bridge_message,
)
from tetherbot.clipboard_policy import image_label, list_preview  # noqa: E402
from tetherbot.clipboard_search import (  # noqa: E402
    choose_search_template,
    desktop_search_inputs,
    open_clip_search,
)
from tetherbot.markdown import Run, render  # noqa: E402
from tetherbot.model import looks_like_secret  # noqa: E402
from tetherbot.todos import PALETTE  # noqa: E402
from tetherbot.ui_settings import EXTENSION_UUID, load_ui_settings  # noqa: E402
from tetherbot.window_launch import APP_ID  # noqa: E402
from tetherbot.window_query import (  # noqa: E402
    MIN_WINDOW_HEIGHT,
    SORTS,
    VIEWS,
    bot_detail_line,
    can_mark_done,
    center_bar_span,
    copy_body,
    copy_title,
    copy_todo,
    due_undo_keys,
    fitted_window_height,
    format_duration,
    format_time_record,
    format_top_bar,
    format_tracked,
    is_read_only,
    list_filter,
    merge_undo_items,
    note_done,
    note_payload,
    parse_start_clock,
    parse_tracked_total,
    properties_need_reload,
    safe_http_url,
    source_line,
    timer_item_key,
    undo_fraction,
)

BUS_NAME = "io.github.grokkinggrok.TetherBot1"
OBJECT_PATH = "/io/github/grokkinggrok/TetherBot1"
INTERFACE = "io.github.grokkinggrok.TetherBot1"
LINGER_MS = 60_000
_CLIP_WINDOW = re.compile(
    r"^(clip-edit|clip-tag|clip-context):(c-[0-9a-f]{8})$"
)
_EDITOR_TITLES = {
    "clip-edit": "Edit clip",
    "clip-tag": "Tag clip",
    "clip-context": "Make a todo with context",
}
_EDITOR_SIZE = {
    "clip-edit": (480, 320),
    "clip-tag": (320, 360),
    "clip-context": (360, 320),
}
_EFFORT_TITLES = {"low": "Low", "medium": "Medium", "high": "High"}


def _clip_window_action(key: str) -> tuple[str, str] | None:
    """``clip-edit``, ``clip-tag``, or ``clip-context`` plus one clipboard id."""

    if not isinstance(key, str):
        return None
    match = _CLIP_WINDOW.fullmatch(key)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _pad_box(box: Gtk.Widget) -> None:
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)


def _editor_heading(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("heading")
    label.set_halign(Gtk.Align.START)
    return label


def _mapped_popover(root: Gtk.Widget) -> Gtk.Popover | None:
    """A dropdown popover that is on screen under this widget."""

    found: list[Gtk.Popover] = []

    def walk(widget: Gtk.Widget | None) -> None:
        if widget is None or found:
            return
        if isinstance(widget, Gtk.Popover) and widget.get_mapped():
            found.append(widget)
            return
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(root)
    return found[0] if found else None


def _find_clip(entries: object, ident: str) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for row in entries:
        if isinstance(row, dict) and row.get("id") == ident:
            return row
    return None


def _entry_tags(entry: dict[str, Any]) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    for tag in entry.get("tags") or []:
        if not isinstance(tag, dict) or not isinstance(tag.get("name"), str):
            continue
        color = tag.get("color")
        tags.append(
            {"name": tag["name"], "color": color if isinstance(color, str) else "gray"}
        )
    return tags


def _clip_editor_block(kind: str, entry: dict[str, Any]) -> str | None:
    image = entry.get("kind") == "image"
    masked = entry.get("masked") is True
    if kind == "clip-edit" and image:
        return "Images are not edited"
    if kind == "clip-edit" and masked:
        return "Hidden passwords are not edited"
    if kind == "clip-tag" and masked:
        return "Hidden passwords are not tagged"
    if kind == "clip-context" and image:
        return "Images are not sent"
    if kind == "clip-context" and masked:
        return "Hidden passwords are not sent"
    return None


def _load_clip_entries(
    client: Any,
    done: Callable[[list[dict[str, Any]], BridgeError | None], None],
) -> None:
    if hasattr(client, "load_clipboard"):
        client.load_clipboard(done)
        return
    if hasattr(client, "get_clipboard"):
        try:
            done(client.get_clipboard(), None)
        except BridgeError as exc:
            done([], exc)
        return
    done([], BridgeError("Bridge not running"))


def _build_text_editor(
    title: str,
    text: str,
    *,
    editable: bool,
    on_save: Callable[[str], None] | None,
) -> Gtk.Box:
    view = Gtk.TextView(
        editable=editable,
        cursor_visible=editable,
        wrap_mode=Gtk.WrapMode.WORD_CHAR,
        vexpand=True,
    )
    view.set_hexpand(True)
    view.get_buffer().set_text(text)
    scrolled = Gtk.ScrolledWindow(child=view)
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_propagate_natural_height(True)
    scrolled.set_max_content_height(220)
    scrolled.set_min_content_height(80)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_size_request(456, -1)
    _pad_box(box)
    box.append(_editor_heading(title))
    box.append(scrolled)
    if editable and on_save is not None:
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.set_halign(Gtk.Align.END)

        def _clicked(_button: Gtk.Button) -> None:
            buffer = view.get_buffer()
            on_save(
                buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            )

        save.connect("clicked", _clicked)
        box.append(save)
    return box


def _focus_tag_entry(entry: Gtk.Widget | None) -> None:
    """Move the caret into the tag field.

    GTK 4 keeps that focus on the entry's inner text. A popover does not
    do this on its own, and the button click that opened it takes focus back.
    """

    if isinstance(entry, Gtk.Entry) and entry.get_parent() is not None:
        entry.grab_focus()


def _tag_entry_focused(widget: Gtk.Widget | None) -> bool:
    while widget is not None:
        if getattr(widget, "is_tag_value", False):
            return True
        widget = widget.get_parent()
    return False


def _build_tag_editor(
    tags: list[dict[str, str]],
    on_save: Callable[[list[dict[str, str]]], None],
) -> Gtk.Box:
    working = [dict(tag) for tag in tags]
    rows = Gtk.ListBox()
    name_row = Gtk.Entry(placeholder_text="Tag")
    name_row.set_hexpand(True)
    name_row.set_editable(True)
    name_row.set_sensitive(True)
    name_row.set_can_focus(True)
    name_row.set_focus_on_click(True)
    name_row.set_activates_default(False)
    name_row.is_tag_value = True
    color_row = Gtk.DropDown.new_from_strings([name.title() for name in PALETTE])
    add = Gtk.Button(label="Add")
    save = Gtk.Button(label="Save")
    save.add_css_class("suggested-action")

    def rebuild() -> None:
        while (child := rows.get_first_child()) is not None:
            rows.remove(child)
        for index, tag in enumerate(working):
            line = Gtk.Box(spacing=6)
            line.set_margin_top(4)
            line.set_margin_bottom(4)
            line.set_margin_start(8)
            line.set_margin_end(8)
            line.append(_chip(tag["name"], tag.get("color") or "gray"))
            remove = Gtk.Button(label="Remove")
            remove.connect("clicked", lambda _button, item=index: drop(item))
            line.append(remove)
            rows.append(line)

    def drop(index: int) -> None:
        if 0 <= index < len(working):
            working.pop(index)
            rebuild()

    def add_tag(_widget: Gtk.Widget) -> None:
        name = " ".join(name_row.get_text().split())
        if not name or len(name) > 40:
            return
        if any(tag["name"].casefold() == name.casefold() for tag in working):
            return
        selected = color_row.get_selected()
        color = PALETTE[selected] if 0 <= selected < len(PALETTE) else PALETTE[0]
        working.append({"name": name, "color": color})
        name_row.set_text("")
        rebuild()
        _focus_tag_entry(name_row)

    def save_tags(_button: Gtk.Button) -> None:
        on_save([dict(tag) for tag in working])

    def _focus_on_map(_widget: Gtk.Entry) -> None:
        _focus_tag_entry(name_row)

    def _focus_when_pointer_enters(*_args: object) -> None:
        _focus_tag_entry(name_row)

    def _focus_after_click() -> bool:
        _focus_tag_entry(name_row)
        return False

    add.connect("clicked", add_tag)
    name_row.connect("activate", add_tag)
    name_row.connect("map", _focus_on_map)
    pointer = Gtk.EventControllerMotion()
    pointer.connect("enter", _focus_when_pointer_enters)
    name_row.add_controller(pointer)
    GLib.idle_add(_focus_after_click)
    save.connect("clicked", save_tags)
    editor = Gtk.Box(spacing=6)
    editor.append(name_row)
    editor.append(color_row)
    editor.append(add)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_propagate_natural_height(True)
    scroller.set_max_content_height(200)
    scroller.set_child(rows)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_size_request(320, -1)
    _pad_box(box)
    box.append(_editor_heading("Tags"))
    box.append(scroller)
    box.append(editor)
    box.append(save)
    box.tag_entry = name_row
    rebuild()
    return box


def _build_context_editor(
    effort: str,
    bot_names: list[str],
    on_send: Callable[[str], None],
    on_cancel: Callable[[], None],
) -> Gtk.Box:
    if effort not in _EFFORT_TITLES:
        effort = "low"
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_size_request(320, -1)
    _pad_box(box)
    box.append(_editor_heading("Make a todo with context"))
    effort_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    effort_row.set_halign(Gtk.Align.START)
    effort_row.append(Gtk.Label(label="Effort:"))
    level = Gtk.Label(label=_EFFORT_TITLES[effort])
    level.add_css_class(f"tether-effort-{effort}")
    level.set_halign(Gtk.Align.START)
    effort_row.append(level)
    box.append(effort_row)
    bots = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    leader = None
    buttons: list[Gtk.CheckButton] = []
    for name in bot_names:
        choice = Gtk.CheckButton(label=name)
        if leader is None:
            leader = choice
            choice.set_active(True)
        else:
            choice.set_group(leader)
        bots.append(choice)
        buttons.append(choice)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_propagate_natural_height(True)
    scroller.set_max_content_height(220)
    scroller.set_child(bots)
    box.append(scroller)
    actions = Gtk.Box(spacing=6)
    actions.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label="Cancel")
    send = Gtk.Button(label="Send")
    send.add_css_class("suggested-action")

    def _cancel(_button: Gtk.Button) -> None:
        on_cancel()

    def _send(_button: Gtk.Button) -> None:
        target = "primary"
        for button in buttons:
            if not button.get_active():
                continue
            chosen = button.get_label()
            if isinstance(chosen, str) and chosen:
                target = chosen
            break
        on_send(target)

    cancel.connect("clicked", _cancel)
    send.connect("clicked", _send)
    actions.append(cancel)
    actions.append(send)
    box.append(actions)
    box.effort_level = level
    box.bot_buttons = buttons
    box.send_button = send
    box.cancel_button = cancel
    return box


def _build_clip_image_preview(path: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    _pad_box(box)
    box.append(_editor_heading("Preview"))
    picture = Gtk.Picture(hexpand=True, vexpand=True)
    if hasattr(Gtk, "ContentFit"):
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
    picture.set_size_request(480, 320)
    loaded = False
    if path and Path(path).is_file():
        try:
            picture.set_paintable(Gdk.Texture.new_from_filename(path))
            loaded = True
        except Exception:
            loaded = False
    if loaded:
        box.append(picture)
        return box
    missing = Gtk.Label(label="That image is not available")
    missing.set_halign(Gtk.Align.CENTER)
    missing.set_valign(Gtk.Align.CENTER)
    missing.set_size_request(480, 120)
    box.append(missing)
    return box
_SORT_LABELS = ("Due", "Priority", "Created", "Updated")
_VIEW_LABELS = {
    "all": "All",
    "mine": "Mine",
    "bots": "Bots",
    "waiting": "Waiting",
    "today": "Today",
}

_CSS = """
.tether-chip {
  border-radius: 999px;
  padding: 1px 8px;
  font-weight: 600;
}
.tone-red { color: #a51d2d; background-color: alpha(#a51d2d, 0.16); }
.tone-orange { color: #c64600; background-color: alpha(#c64600, 0.16); }
.tone-amber { color: #865e0b; background-color: alpha(#e5a50a, 0.22); }
.tone-yellow { color: #8f5902; background-color: alpha(#f5c211, 0.28); }
.tone-green { color: #1b7a3a; background-color: alpha(#2ec27e, 0.16); }
.tone-teal { color: #0d7377; background-color: alpha(#1a9a9c, 0.16); }
.tone-blue { color: #1c71d8; background-color: alpha(#1c71d8, 0.14); }
.tone-purple { color: #613583; background-color: alpha(#813d9c, 0.16); }
.tone-pink { color: #a31863; background-color: alpha(#e05a9a, 0.16); }
.tone-gray, .tone-neutral { color: #5e5c64; background-color: alpha(#9a9996, 0.18); }
.tether-dark .tone-red { color: #ff8b8b; background-color: alpha(#ff8b8b, 0.18); }
.tether-dark .tone-orange { color: #ffb07a; background-color: alpha(#ffb07a, 0.18); }
.tether-dark .tone-amber { color: #f8d06a; background-color: alpha(#f8d06a, 0.18); }
.tether-dark .tone-yellow { color: #f9e07a; background-color: alpha(#f9e07a, 0.18); }
.tether-dark .tone-green { color: #8ff0a4; background-color: alpha(#8ff0a4, 0.16); }
.tether-dark .tone-teal { color: #93ddd6; background-color: alpha(#93ddd6, 0.16); }
.tether-dark .tone-blue { color: #99c1f1; background-color: alpha(#99c1f1, 0.16); }
.tether-dark .tone-purple { color: #d7b4f3; background-color: alpha(#d7b4f3, 0.16); }
.tether-dark .tone-pink { color: #f7b2d8; background-color: alpha(#f7b2d8, 0.16); }
.tether-dark .tone-gray, .tether-dark .tone-neutral {
  color: #deddda;
  background-color: alpha(#deddda, 0.12);
}
.tether-clip-dot {
  background-color: transparent;
  padding: 0;
  font-size: 8px;
}
.tether-dark .tether-clip-dot {
  background-color: transparent;
}
.tether-clip-action {
  padding: 4px;
  min-width: 28px;
  min-height: 28px;
}
.tether-clip-thumb {
  min-width: 48px;
  min-height: 48px;
}
.tether-effort-low { color: @success_color; }
.tether-effort-medium { color: @warning_color; }
.tether-effort-high { color: @error_color; }
separator.tether-clip-sep {
  min-width: 1px;
  margin-top: 6px;
  margin-bottom: 6px;
  opacity: 0.35;
}
.tether-row-done { opacity: 0.7; }
.tether-source { opacity: 0.75; }
.tether-dot { font-size: 0.85em; }
.tether-dot-ok, .tether-dot-idle { color: #26a269; }
.tether-dot-degraded, .tether-dot-offline,
.tether-dot-paused, .tether-dot-needs_you { color: #e5a50a; }
.tether-dot-working { color: #1c71d8; }
.tether-dot-failed_closed, .tether-dot-unconfigured,
.tether-dot-error { color: #c01c28; }
.tether-dot-unknown { color: #9a9996; }
.tether-dark .tether-dot-ok, .tether-dark .tether-dot-idle { color: #8ff0a4; }
.tether-dark .tether-dot-degraded,
.tether-dark .tether-dot-offline,
.tether-dark .tether-dot-paused,
.tether-dark .tether-dot-needs_you { color: #f8d06a; }
.tether-dark .tether-dot-working { color: #99c1f1; }
.tether-dark .tether-dot-failed_closed,
.tether-dark .tether-dot-unconfigured,
.tether-dark .tether-dot-error { color: #ff8b8b; }
.tether-undo { min-width: 4.5em; }
.tether-detail-undo { min-width: 0; }
progressbar.tether-undo-bar { min-height: 24px; }
progressbar.tether-undo-bar > trough {
  min-height: 24px;
  border: none;
  border-radius: 6px;
  background-color: transparent;
}
progressbar.tether-undo-bar > trough > progress {
  min-height: 24px;
  border: none;
  border-radius: 6px;
  background-color: alpha(#1c71d8, 0.35);
}
"""

_DOT_STATES = frozenset(
    {
        "ok",
        "idle",
        "degraded",
        "offline",
        "paused",
        "needs_you",
        "working",
        "failed_closed",
        "unconfigured",
        "error",
    }
)


def _bot_id(value: object) -> str:
    """A feed bot id, or empty when the value is not one."""

    if not isinstance(value, str) or not value or len(value) > 64:
        return ""
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    if any(char not in allowed for char in value):
        return ""
    return value


class BridgeError(Exception):
    """The session bus call did not succeed. The message is safe to show."""


ListDone = Callable[
    [list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], BridgeError | None],
    None,
]


class BridgeClient:
    """D-Bus calls the window is allowed to make."""

    def __init__(self) -> None:
        self._proxy: Gio.DBusProxy | None = None
        self._listener: Callable[[], None] | None = None
        self._clipboard_listener: Callable[[], None] | None = None
        self._generation = 0
        self._signal_idle = 0
        self._waiting: tuple[int, dict[str, Any], Callable[..., None]] | None = None

    def set_listener(self, listener: Callable[[], None]) -> None:
        self._listener = listener

    def set_clipboard_listener(self, listener: Callable[[], None]) -> None:
        self._clipboard_listener = listener

    def get_items(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        raw = self._call("GetItems", "(s)", (json.dumps(spec),))
        return _object_list(raw)

    def get_tags(self) -> list[dict[str, Any]]:
        return _object_list(self._call("GetTags", "()", ()))

    def get_item(self, key: str) -> dict[str, Any]:
        raw = self._call("GetItem", "(s)", (key,))
        if not raw:
            raise BridgeError("item not found")
        item = json.loads(raw[0])
        if not isinstance(item, dict):
            raise BridgeError("item not found")
        return item

    def bots(self) -> list[dict[str, Any]]:
        self._ensure()
        return self._bots_cached()

    def mark_done(self, key: str, note: str = "") -> str:
        args = "{}"
        if isinstance(note, str) and note.strip():
            args = json.dumps({"note": note.strip()})
        raw = self._call("PerformAction", "(sss)", (key, "done", args))
        return raw[0] if raw else ""

    def undo(self, key: str) -> dict[str, Any]:
        raw = self._call("Undo", "(s)", (key,))
        if not raw:
            return {}
        parsed = json.loads(raw[0])
        return parsed if isinstance(parsed, dict) else {}

    def send_note(self, key: str) -> str:
        bot, payload = note_payload(key)
        raw = self._call("SendToBot", "(ss)", (bot, payload))
        return raw[0] if raw else ""

    def start_timer(self, item_key: str) -> dict[str, Any]:
        return _object_dict(self._call("StartTimer", "(s)", (item_key,)))

    def stop_timer(self) -> dict[str, Any]:
        return _object_dict(self._call("StopTimer", "()", ()))

    def adjust_start(self, delta_s: int) -> dict[str, Any]:
        return _object_dict(self._call("AdjustTimerStart", "(x)", (delta_s,)))

    def set_start(self, started_at: int) -> dict[str, Any]:
        return _object_dict(self._call("SetTimerStart", "(x)", (started_at,)))

    def attach_timer(self, item_key: str) -> dict[str, Any]:
        return _object_dict(self._call("AssignTimer", "(s)", (item_key,)))

    def dismiss_timer(self) -> dict[str, Any]:
        return _object_dict(self._call("DismissTimer", "()", ()))

    def get_item_time(self, item_key: str) -> dict[str, Any]:
        return _object_dict(self._call("GetItemTime", "(s)", (item_key,)))

    def set_tracked_total(self, item_key: str, total_s: int) -> dict[str, Any]:
        return _object_dict(self._call("SetTrackedTotal", "(sx)", (item_key, total_s)))

    def delete_time_record(self, item_key: str, record_id: str) -> dict[str, Any]:
        return _object_dict(self._call("DeleteTimeRecord", "(ss)", (item_key, record_id)))

    def get_clipboard(self, query: str = "") -> list[dict[str, Any]]:
        return _object_list(self._call("GetClipboard", "(s)", (query,)))

    def delete_clipboard(self, entry_id: str) -> bool:
        raw = self._call("DeleteClipboard", "(s)", (entry_id,))
        return bool(raw and raw[0])

    def clear_clipboard(self) -> bool:
        raw = self._call("ClearClipboard", "()", ())
        return bool(raw and raw[0])

    def pin_clipboard(self, entry_id: str, pinned: bool) -> bool:
        raw = self._call("PinClipboard", "(sb)", (entry_id, pinned))
        return bool(raw and raw[0])

    def set_clipboard_tags(self, entry_id: str, tags: list[dict[str, str]]) -> bool:
        raw = self._call("SetClipboardTags", "(ss)", (entry_id, json.dumps(tags)))
        return bool(raw and raw[0])

    def edit_clipboard(self, entry_id: str, text: str) -> bool:
        raw = self._call("EditClipboard", "(ss)", (entry_id, text))
        return bool(raw and raw[0])

    def send_clipboard(self, entry_id: str, action: str, target_bot: str = "primary") -> str:
        bot = target_bot if isinstance(target_bot, str) and target_bot else "primary"
        raw = self._call("SendClipboard", "(sss)", (entry_id, action, bot))
        if not raw or not isinstance(raw[0], str):
            raise BridgeError("Not sent")
        return raw[0]

    def get_clipboard_image(self, entry_id: str) -> tuple[str, bytes]:
        """Original image bytes for copy-back. A missing image has no path."""

        raw = self._call("GetClipboardImage", "(s)", (entry_id,))
        if len(raw) < 2 or not isinstance(raw[0], str):
            raise BridgeError("That image is not available")
        blob = _as_bytes(raw[1])
        if blob is None:
            raise BridgeError("That image is not available")
        return raw[0], blob

    def load_clipboard(
        self,
        done: Callable[[list[dict[str, Any]], BridgeError | None], None],
    ) -> None:
        """Read clipboard history without blocking the window loop."""

        def _done(raw: tuple[Any, ...] | None, error: BridgeError | None) -> None:
            if error is not None or raw is None:
                done([], error or BridgeError("Bridge not running"))
                return
            try:
                done(_object_list(raw), None)
            except (json.JSONDecodeError, TypeError):
                done([], BridgeError("Clipboard history could not be read"))

        if self._proxy is None:
            done([], BridgeError("Bridge not running"))
            return
        self._call_async("GetClipboard", "(s)", ("",), _done)

    def load_timer(self, done: Callable[[dict[str, Any], BridgeError | None], None]) -> None:
        """Read the stopwatch without blocking the first paint."""

        def _done(
            raw: tuple[Any, ...] | None,
            error: BridgeError | None,
        ) -> None:
            if error is not None or not raw:
                done({}, error or BridgeError("Bridge not running"))
                return
            try:
                parsed = json.loads(raw[0])
            except (json.JSONDecodeError, IndexError, TypeError):
                done({}, BridgeError("The saved timer could not be read"))
                return
            done(parsed if isinstance(parsed, dict) else {}, None)

        self._call_async("GetTimer", "()", (), _done)

    def load_list(self, spec: dict[str, Any], done: ListDone) -> None:
        """Load items, tags, and bots without blocking the window loop."""

        self._generation += 1
        generation = self._generation
        self._waiting = (generation, spec, done)
        if self._proxy is not None:
            self._load_items()
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self._finish_load(generation, BridgeError("Bridge not running"))
            return
        def _ready(source: object, result: Gio.AsyncResult, generation: int = generation) -> None:
            self._on_proxy(generation, source, result)

        Gio.DBusProxy.new(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            None,
            _ready,
        )

    def _on_proxy(self, generation: int, _source: object, result: Gio.AsyncResult) -> None:
        try:
            proxy = Gio.DBusProxy.new_finish(result)
        except GLib.Error:
            self._finish_load(generation, BridgeError("Bridge not running"))
            return
        if generation != self._generation:
            return
        self._proxy = proxy
        self._proxy.connect("g-signal", self._on_signal)
        self._proxy.connect("g-properties-changed", self._on_properties)
        self._load_items()

    def _load_items(self) -> None:
        waiting = self._waiting
        if waiting is None or self._proxy is None:
            return
        generation, spec, _done = waiting
        if generation != self._generation:
            return

        def _done(
            raw: tuple[Any, ...] | None,
            error: BridgeError | None,
            generation: int = generation,
        ) -> None:
            self._on_items(generation, raw, error)

        self._call_async("GetItems", "(s)", (json.dumps(spec),), _done)

    def _on_items(
        self,
        generation: int,
        raw: tuple[Any, ...] | None,
        error: BridgeError | None,
    ) -> None:
        if generation != self._generation:
            return
        if error is not None or raw is None:
            self._finish_load(generation, error or BridgeError("Bridge not running"))
            return
        items = _object_list(raw)

        def _done(
            reply: tuple[Any, ...] | None,
            err: BridgeError | None,
            generation: int = generation,
            items: list[dict[str, Any]] = items,
        ) -> None:
            self._on_tags(generation, items, reply, err)

        self._call_async("GetTags", "()", (), _done)

    def _on_tags(
        self,
        generation: int,
        items: list[dict[str, Any]],
        raw: tuple[Any, ...] | None,
        error: BridgeError | None,
    ) -> None:
        if generation != self._generation:
            return
        if error is not None or raw is None:
            self._finish_load(generation, error or BridgeError("Bridge not running"))
            return
        self._finish_load(generation, None, items, _object_list(raw), self._bots_cached())

    def _finish_load(
        self,
        generation: int,
        error: BridgeError | None,
        items: list[dict[str, Any]] | None = None,
        tags: list[dict[str, Any]] | None = None,
        bots: list[dict[str, Any]] | None = None,
    ) -> None:
        if generation != self._generation:
            return
        waiting = self._waiting
        if waiting is None:
            return
        _generation, _spec, done = waiting
        self._waiting = None
        done(items or [], tags or [], bots or [], error)

    def _bots_cached(self) -> list[dict[str, Any]]:
        if self._proxy is None:
            return []
        variant = self._proxy.get_cached_property("Bots")
        if variant is None:
            return []
        parsed = json.loads(variant.unpack())
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed if isinstance(row, dict)]

    def _call_async(
        self,
        method: str,
        signature: str,
        args: tuple[Any, ...],
        done: Callable[[tuple[Any, ...] | None, BridgeError | None], None],
    ) -> None:
        proxy = self._proxy
        if proxy is None:
            done(None, BridgeError("Bridge not running"))
            return

        def _done(_proxy: Gio.DBusProxy, result: Gio.AsyncResult) -> None:
            try:
                reply = proxy.call_finish(result)
            except GLib.Error as exc:
                done(None, BridgeError(exc.message or "Bridge not running"))
                return
            if reply is None:
                done((), None)
                return
            unpacked = reply.unpack()
            if isinstance(unpacked, tuple):
                done(unpacked, None)
                return
            done((unpacked,), None)

        proxy.call(
            method,
            GLib.Variant(signature, args),
            Gio.DBusCallFlags.NONE,
            8000,
            None,
            _done,
        )

    def _ensure(self) -> None:
        if self._proxy is None:
            raise BridgeError("Bridge not running")

    def _call(self, method: str, signature: str, args: tuple[Any, ...]) -> tuple[Any, ...]:
        self._ensure()
        assert self._proxy is not None
        try:
            result = self._proxy.call_sync(
                method,
                GLib.Variant(signature, args),
                Gio.DBusCallFlags.NONE,
                8000,
                None,
            )
        except GLib.Error as exc:
            message = exc.message or "Bridge not running"
            raise BridgeError(message) from exc
        if result is None:
            return ()
        unpacked = result.unpack()
        if isinstance(unpacked, tuple):
            return unpacked
        return (unpacked,)

    def _on_signal(self, _proxy: Gio.DBusProxy, _sender: str, signal: str, _params: Any) -> None:
        if signal == "ClipboardChanged":
            listener = self._clipboard_listener
            if listener is not None:
                listener()
            return
        if signal in {"ItemsChanged", "TimerChanged"}:
            self._schedule_listener()

    def _on_properties(self, _proxy: Any, changed: Any, invalidated: Any) -> None:
        names = [*_variant_names(changed), *_variant_names(invalidated)]
        self.note_properties(names)

    def note_properties(self, names: object) -> None:
        """Reload when ``Bots`` changed. Safe to call from a test."""

        if properties_need_reload(names):
            self._schedule_listener()

    def _schedule_listener(self) -> None:
        """Coalesce bridge signals into one reload on the next idle."""

        if self._listener is None or self._signal_idle:
            return
        self._signal_idle = GLib.idle_add(self._emit_listener)

    def _emit_listener(self) -> bool:
        self._signal_idle = 0
        listener = self._listener
        if listener is not None:
            listener()
        return GLib.SOURCE_REMOVE


WINDOW_DEFAULT_WIDTH = 1520
WINDOW_MIN_WIDTH = 1400


class TodoWindow(Adw.ApplicationWindow):
    """List, filters, and a Markdown detail pane."""

    def __init__(self, app: Adw.Application, client: Any) -> None:
        super().__init__(application=app, title="TetherBot")
        self.set_default_size(WINDOW_DEFAULT_WIDTH, 800)
        self.set_size_request(WINDOW_MIN_WIDTH, 680)
        self.set_icon_name(APP_ID)
        self.client = client
        self._filling = False
        self._view = "all"
        self._page = "todos"
        self._clip_query = ""
        self._clip_tag = ""
        self._clip_tag_guard = False
        self._clip_search_ready = False
        self._clip_search_kind = "none"
        self._clip_search_template: str | None = None
        self._clip_entries: list[dict[str, Any]] = []
        self._clip_gen = 0
        self._clip_pending: tuple[str, str] | None = None
        self._clip_dialog: Adw.AlertDialog | None = None
        self._clip_popover: Gtk.Popover | None = None
        self._clip_context_dialog: Gtk.Popover | None = None
        self._popover_reload = False
        self._sort = "due"
        self._query = ""
        self._bot_query = ""
        self._bot_filter: set[str] = set()
        self._known_bots: list[dict[str, Any]] = []
        self._tags_on: set[str] = set()
        self._show_done = False
        self._outbound: dict[str, bool] = {}
        self._rows: dict[str, Gtk.ListBoxRow] = {}
        self._wanted = ""
        self._current: dict[str, Any] | None = None
        self._items: list[dict[str, Any]] = []
        self._timer: dict[str, Any] = {"state": "idle"}
        self._switch_ask: dict[str, Any] | None = None
        self._editing_start = False
        self._timer_generation = 0
        self._link_tags: dict[str, Gtk.TextTag] = {}
        self._undo_holds: dict[str, dict[str, Any]] = {}
        self._kept_secret_note: tuple[str, str] | None = None
        self._undo_span = 5000
        self._undo_bars: list[tuple[Gtk.ProgressBar, int]] = []
        self._undo_source = 0
        self._undo_paint = 0
        self._after_send_idle = 0
        self._after_send_refresh = False
        self._done_until = 0
        self._note_until = 0
        self._list_hovered = False
        self._guard_rows = False
        self._drop_idle = 0
        self._drop_wait = False
        self._doomed: list[Gtk.ListBoxRow] = []
        self._height_fitted = False
        self._fit_width = 0
        self._fit_correct = 0
        self._user_sized = False
        self._fitting_height = False
        self._saw_fitted_layout = False
        self._last_layout: tuple[int, int] | None = None
        self._size_watch_id = 0
        self._detail_until = 0
        self.open_uri = _open_uri
        self._build()
        self.connect("close-request", self._on_window_close)
        self.connect("realize", self._bind_size_watch)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        if hasattr(client, "set_listener"):
            client.set_listener(self.refresh)
        if hasattr(client, "set_clipboard_listener"):
            client.set_clipboard_listener(self._on_clipboard_changed)

    def _build(self) -> None:
        self.titlebar = Adw.HeaderBar()
        self.titlebar.set_title_widget(
            Adw.WindowTitle.new("TetherBot", "Unofficial. Not affiliated with xAI.")
        )
        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(300)
        self.split.set_max_sidebar_width(460)
        self.toasts.set_child(self.split)
        self.toolbar = Adw.ToolbarView()
        self.toolbar.add_top_bar(self.titlebar)
        self.toolbar.set_content(self.toasts)
        self.set_content(self.toolbar)
        style = Adw.StyleManager.get_default()
        self._sync_theme(style)
        style.connect("notify::dark", self._sync_theme)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720px"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)

        self.search = Gtk.SearchEntry(placeholder_text="Search titles, notes, and tags")
        self.search.connect("changed", self._on_search)
        self._page_buttons = self._build_pages()
        self._view_buttons = self._build_views()
        self.tag_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False)
        self.tag_box.set_max_children_per_line(8)
        self._clear = Gtk.Button(label="Clear")
        self._clear.set_sensitive(False)
        self._clear.connect("clicked", self._on_clear_tags)
        self.bot_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False)
        self.bot_box.set_max_children_per_line(8)
        self.bot_box.set_visible(False)
        tag_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tag_wrap.append(self.tag_box)
        tag_wrap.append(self.bot_box)
        tag_wrap.append(self._clear)
        self.bot_search = Gtk.SearchEntry(placeholder_text="Filter bots by name")
        self.bot_search.set_visible(False)
        self.bot_search.connect("changed", self._on_bot_search)
        self.clip_search = Gtk.SearchEntry(placeholder_text="Search clipboard and tags")
        self.clip_search.set_visible(True)
        self.clip_search.connect("search-changed", self._on_clip_search)
        self.clip_tag = Gtk.DropDown.new_from_strings(["All tags"])
        self.clip_tag.connect("notify::selected", self._on_clip_tag)
        self.clip_clear = Gtk.Button(label="Clear history")
        self.clip_clear.connect("clicked", lambda _button: self._confirm_clear_clipboard())
        self._clip_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._clip_controls.set_visible(False)
        self._clip_controls.append(self.clip_search)
        self._clip_controls.append(self.clip_tag)
        self._clip_controls.append(self.clip_clear)
        self.sort_drop = Gtk.DropDown.new_from_strings(list(_SORT_LABELS))
        self.sort_drop.connect("notify::selected", self._on_sort)
        self.show_done = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.show_done.connect("notify::active", self._on_show_done)
        sort_row = Gtk.Box(spacing=12)
        sort_row.append(Gtk.Label(label="Sort", xalign=0))
        sort_row.append(self.sort_drop)
        done_row = Gtk.Box(spacing=12)
        done_label = Gtk.Label(label="Show done", xalign=0, hexpand=True)
        done_row.append(done_label)
        done_row.append(self.show_done)
        self.banner = Adw.Banner(revealed=False)
        self.timer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.timer_box.set_visible(False)
        self.timer_label = Gtk.Label(xalign=0, wrap=True)
        self.timer_actions = Gtk.Box(spacing=6)
        self.edit_start_box = Gtk.Box(spacing=6)
        self.edit_start_box.set_visible(False)
        for label, delta in (("-5m", -300), ("-15m", -900), ("-30m", -1800)):
            button = Gtk.Button(label=label)
            button.connect("clicked", self._on_adjust_start, delta)
            self.edit_start_box.append(button)
        self.start_entry = Gtk.Entry(placeholder_text="HH:MM")
        self.start_entry.set_max_width_chars(6)
        self.start_entry.connect("activate", self._on_set_start)
        set_start = Gtk.Button(label="Set start")
        set_start.connect("clicked", self._on_set_start)
        cancel_edit = Gtk.Button(label="Cancel")
        cancel_edit.connect("clicked", lambda _button: self._set_editing_start(False))
        self.edit_start_box.append(self.start_entry)
        self.edit_start_box.append(set_start)
        self.edit_start_box.append(cancel_edit)
        self.timer_box.append(self.timer_label)
        self.timer_box.append(self.timer_actions)
        self.timer_box.append(self.edit_start_box)
        self.switch_box = Gtk.Box(spacing=8)
        self.switch_box.set_visible(False)
        self.switch_label = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.switch_button = Gtk.Button(label="Switch")
        self.switch_button.connect("clicked", lambda _button: self._confirm_switch())
        self.switch_cancel = Gtk.Button(label="Cancel")
        self.switch_cancel.connect("clicked", lambda _button: self._cancel_switch())
        self.switch_box.append(self.switch_label)
        self.switch_box.append(self.switch_button)
        self.switch_box.append(self.switch_cancel)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("boxed-list")
        self.list.connect("row-selected", self._on_row_selected)
        self.list.connect("row-activated", self._on_row_activated)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_args: self._set_list_hover(True))
        hover.connect("leave", lambda *_args: self._set_list_hover(False))
        self.list.add_controller(hover)
        self._todo_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._todo_controls.append(self.search)
        self._todo_controls.append(self._view_buttons)
        self._todo_controls.append(tag_wrap)
        self._todo_controls.append(sort_row)
        self._todo_controls.append(done_row)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        controls.set_margin_start(12)
        controls.set_margin_end(12)
        controls.set_margin_top(12)
        controls.set_margin_bottom(6)
        controls.append(self.banner)
        controls.append(self.timer_box)
        controls.append(self.switch_box)
        controls.append(self._page_buttons)
        controls.append(self._todo_controls)
        controls.append(self.bot_search)
        controls.append(self._clip_controls)
        self._list_controls = controls
        scrolled = Gtk.ScrolledWindow(vexpand=True, child=self.list)
        scrolled.set_propagate_natural_height(False)
        scrolled.set_propagate_natural_width(False)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._list_scroll = scrolled
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._sidebar_box = sidebar_box
        sidebar_box.append(controls)
        sidebar_box.append(scrolled)
        sidebar_bar = Adw.ToolbarView(content=sidebar_box)
        self.split.set_sidebar(Adw.NavigationPage.new(sidebar_bar, "Todos"))

        self.back = Gtk.Button(icon_name="go-previous-symbolic")
        self.back.set_tooltip_text("Back")
        self.back.set_visible(False)
        self.back.connect("clicked", lambda _button: self.split.set_show_content(False))
        self.split.connect("notify::collapsed", self._on_collapsed)
        self.detail_title = Gtk.Label(xalign=0, wrap=True, selectable=True, hexpand=True)
        self.detail_title.set_valign(Gtk.Align.START)
        self.detail_title.add_css_class("title-1")
        self.copy_title_button = _copy_icon("Copy title")
        self.copy_title_button.connect("clicked", lambda _button: self._copy_title())
        title_row = Gtk.Box(spacing=8)
        title_row.append(self.detail_title)
        title_row.append(self.copy_title_button)
        self.detail_chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE)
        self.detail_chips.set_vexpand(False)
        self.detail_chips.set_valign(Gtk.Align.START)
        self.time_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.time_box.set_visible(False)
        time_row = Gtk.Box(spacing=8)
        time_label = Gtk.Label(label="Tracked", xalign=0)
        self.time_entry = Gtk.Entry(width_chars=8, max_width_chars=10)
        self.time_entry.set_placeholder_text("0:00:00")
        self.time_entry.set_tooltip_text("Tracked total, hours:minutes:seconds")
        self.time_entry.connect("activate", lambda _entry: self._set_tracked())
        self.time_set = Gtk.Button(label="Set")
        self.time_set.set_tooltip_text("Set tracked total")
        self.time_set.connect("clicked", lambda _button: self._set_tracked())
        time_row.append(time_label)
        time_row.append(self.time_entry)
        time_row.append(self.time_set)
        self.time_records = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        time_scroll = Gtk.ScrolledWindow(child=self.time_records)
        time_scroll.set_propagate_natural_height(True)
        time_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        time_scroll.set_max_content_height(132)
        self.time_box.append(time_row)
        self.time_box.append(time_scroll)
        self._time_dialog: Adw.AlertDialog | None = None
        self.buffer = Gtk.TextBuffer()
        _install_style_tags(self.buffer)
        self.text = Gtk.TextView(
            buffer=self.buffer,
            editable=False,
            cursor_visible=False,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            left_margin=2,
            right_margin=2,
            top_margin=4,
        )
        click = Gtk.GestureClick()
        click.connect("released", self._on_text_click)
        self.text.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_text_motion)
        self.text.add_controller(motion)
        body_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True, child=self.text)
        self.copy_body_button = _copy_icon("Copy body")
        self.copy_body_button.connect("clicked", lambda _button: self._copy_body())
        body_row = Gtk.Box(spacing=8)
        body_row.set_vexpand(True)
        body_row.append(body_scroll)
        body_row.append(self.copy_body_button)
        self.note_label = Gtk.Label(label="Note", xalign=0)
        self.note_buffer = Gtk.TextBuffer()
        self.note_view = Gtk.TextView(
            buffer=self.note_buffer,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            accepts_tab=False,
            left_margin=6,
            right_margin=6,
            top_margin=4,
            bottom_margin=4,
        )
        self.note_buffer.connect("changed", lambda _buffer: self._sync_done_note())
        note_scroll = Gtk.ScrolledWindow(child=self.note_view, hexpand=True)
        note_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        note_scroll.set_propagate_natural_height(True)
        note_scroll.set_min_content_height(72)
        note_scroll.set_max_content_height(140)
        note_scroll.add_css_class("frame")
        self.note_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.note_box.set_vexpand(False)
        self.note_box.set_valign(Gtk.Align.START)
        self.note_box.append(self.note_label)
        self.note_box.append(note_scroll)
        self.done_button = _label_button("Done")
        self.done_button.add_css_class("suggested-action")
        self.done_button.connect("clicked", lambda _button: self._done_current())
        self.done_note_button = _label_button("Done with note")
        self.done_note_button.set_sensitive(False)
        self.done_note_button.connect("clicked", lambda _button: self._done_with_note())
        self.done_undo, self._done_bar = _undo_button(detail=True)
        self.done_undo.connect("clicked", lambda _button: self._undo_current())
        self.note_undo, self._note_bar = _undo_button(detail=True)
        self.note_undo.connect("clicked", lambda _button: self._undo_current())
        self.done_stack = _button_slot(self.done_button, self.done_undo)
        self.note_stack = _button_slot(self.done_note_button, self.note_undo)
        self.start_button = _label_button("Start timer")
        self.start_button.connect("clicked", lambda _button: self._start_current())
        self.attach_button = _label_button("Attach timer")
        self.attach_button.connect("clicked", lambda _button: self._attach_current())
        self.copy_button = _label_button("Copy Todo")
        self.copy_button.set_tooltip_text("Copy title and body")
        self.copy_button.connect("clicked", lambda _button: self._copy_current())
        self.ask_button = _label_button("Ask the bot about this")
        self.ask_button.connect("clicked", lambda _button: self._ask_current())
        self.action_row = _action_row(
            self.done_stack,
            self.note_stack,
            self.start_button,
            self.attach_button,
            self.copy_button,
            self.ask_button,
        )
        self.source = Gtk.Label(xalign=0, wrap=True)
        self.source.add_css_class("tether-source")
        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        detail.set_margin_start(16)
        detail.set_margin_end(16)
        detail.set_margin_top(12)
        detail.set_margin_bottom(12)
        detail.append(title_row)
        detail.append(self.detail_chips)
        detail.append(self.time_box)
        detail.append(body_row)
        detail.append(self.note_box)
        detail.append(self.action_row)
        detail.append(self.source)
        detail_bar = Adw.ToolbarView(content=detail)
        self.detail_header = Adw.HeaderBar()
        self.detail_header.set_show_start_title_buttons(False)
        self.detail_header.set_show_end_title_buttons(False)
        self.detail_header.pack_start(self.back)
        self.detail_header.set_visible(False)
        detail_bar.add_top_bar(self.detail_header)
        self.split.set_content(Adw.NavigationPage.new(detail_bar, "Detail"))
        self._show_item(None)
        self._history_watch = self._watch_history()

    def _watch_history(self) -> object | None:
        from tetherbot.ui_settings import watch_history_settings

        return watch_history_settings(self.refresh)

    def refresh(self) -> bool:
        from tetherbot.ui_settings import resolve_ui_settings

        spec = list_filter(
            view=self._view,
            query=self._query,
            tags=sorted(self._tags_on),
            sort=self._sort,
            show_done=self._show_done,
            bots=sorted(self._bot_filter),
            done_seconds=resolve_ui_settings(None).done_history_seconds,
        )
        if hasattr(self.client, "load_list"):
            if not self._items and not self._known_bots:
                self.banner.set_title("Loading…")
                self.banner.set_revealed(True)
            self.client.load_list(spec, self._on_list)
            return GLib.SOURCE_REMOVE
        try:
            items = self.client.get_items(spec)
            tags = self.client.get_tags()
            bots = self.client.bots()
        except BridgeError as exc:
            self.banner.set_title(friendly_bridge_message(exc))
            self.banner.set_revealed(True)
            return GLib.SOURCE_REMOVE
        self._apply_list(items, tags, bots)
        return GLib.SOURCE_REMOVE

    def _on_list(
        self,
        items: list[dict[str, Any]],
        tags: list[dict[str, Any]],
        bots: list[dict[str, Any]],
        error: BridgeError | None,
    ) -> None:
        if error is not None:
            self.banner.set_title(friendly_bridge_message(error))
            self.banner.set_revealed(True)
            return
        self._apply_list(items, tags, bots)
        if self._wanted:
            self._focus_key(self._wanted)

    def _apply_list(
        self,
        items: list[dict[str, Any]],
        tags: list[dict[str, Any]],
        bots: list[dict[str, Any]],
    ) -> None:
        self.banner.set_revealed(False)
        self._outbound = {}
        self._items = items if isinstance(items, list) else []
        self._known_bots = [bot for bot in bots if isinstance(bot, dict)]
        known: set[str] = set()
        for bot in self._known_bots:
            name = bot.get("name")
            if isinstance(name, str) and name:
                known.add(name)
        self._bot_filter &= known
        for bot in bots:
            name = bot.get("name")
            routes = bot.get("routes") if isinstance(bot.get("routes"), dict) else {}
            if isinstance(name, str):
                self._outbound[name] = bool(routes.get("outbound"))
        self._fill_tags(tags if isinstance(tags, list) else [])
        self._fill_bot_chips()
        self._show_page_list()
        self._request_timer()
        self._fit_to_list()

    def select_key(self, key: str) -> None:
        """Raise the window. An empty key shows todos. ``bots`` opens the bot list.

        A clipboard editor key opens that editor and leaves this window where it is.
        """

        clip = _clip_window_action(key)
        if clip is not None:
            self.open_clip_editor(*clip)
            return
        self.present()
        self._clip_pending = None
        if key == "bots":
            self._set_page("bots")
            return
        if key == "clipboard":
            self._set_page("clipboard")
            return
        if self._page != "todos":
            self._set_page("todos")
        if not key:
            if self.split.get_collapsed():
                self.split.set_show_content(False)
            return
        self._filling = True
        self._view = "all"
        self._sort = "due"
        self._query = ""
        self._tags_on.clear()
        self._show_done = False
        self._bot_filter.clear()
        self.search.set_text("")
        self.sort_drop.set_selected(0)
        self.show_done.set_active(False)
        self._sync_views()
        self._filling = False
        self._wanted = key
        self.refresh()
        if not hasattr(self.client, "load_list"):
            self._focus_key(key)
        if self.split.get_collapsed():
            self.split.set_show_content(True)

    def open_clip_editor(self, kind: str, ident: str) -> None:
        app = self.get_application()
        open_editor = getattr(app, "open_clip_editor", None)
        if open_editor is not None:
            open_editor(kind, ident)

    def _focus_key(self, key: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            self.list.select_row(row)
            return
        try:
            item = self.client.get_item(key)
        except BridgeError:
            self._show_item(None)
            return
        self._show_item(item)

    def _fill_tags(self, tags: list[dict[str, Any]]) -> None:
        self._filling = True
        while (child := self.tag_box.get_first_child()) is not None:
            self.tag_box.remove(child)
        known = set()
        for row in tags:
            tag = row.get("tag")
            if not isinstance(tag, str) or not tag:
                continue
            known.add(tag)
            count = row.get("count")
            label = f"@{tag}" if not isinstance(count, int) else f"@{tag} {count}"
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("tether-chip")
            tone = row.get("color") if isinstance(row.get("color"), str) else "gray"
            button.add_css_class(f"tone-{tone}")
            button.set_active(tag in self._tags_on)
            button.connect("toggled", self._on_tag, tag)
            self.tag_box.append(button)
        self._tags_on &= known
        self._clear.set_sensitive(bool(self._tags_on))
        self._filling = False

    def _fill_rows(self, items: list[dict[str, Any]]) -> None:
        selected = self._wanted
        if not selected:
            current = self.list.get_selected_row()
            selected = getattr(current, "item_key", "") if current is not None else ""
            if not isinstance(selected, str):
                selected = ""
        pin_keys = self._pin_keys()
        shown = merge_undo_items(
            items,
            self._undo_holds,
            _now_ms(),
            pin_expired=pin_keys is None or bool(pin_keys),
            pin_keys=pin_keys,
            window_ms=self._undo_span,
        )
        self._undo_bars = [
            (self._done_bar, self._done_until),
            (self._note_bar, self._note_until),
        ]
        rows: list[Gtk.ListBoxRow] = []
        for item in shown:
            key = item.get("key")
            if not isinstance(key, str):
                continue
            rows.append(self._make_row(item))
        self._install_rows(rows, selected if isinstance(selected, str) else "", clear_missing=True)

    def _install_rows(
        self,
        rows: list[Gtk.ListBoxRow],
        selected_key: str,
        *,
        clear_missing: bool,
    ) -> None:
        self._park_list_focus()
        hot = bool(
            self._list_hovered or self._guard_rows or self._doomed or self._any_pointer_row()
        )
        self._filling = True
        self._retire_current(force=not hot)
        self._rows = {}
        for row in rows:
            self.list.append(row)
            key = getattr(row, "item_key", "")
            if isinstance(key, str) and key:
                self._rows[key] = row
        self._filling = False
        if selected_key and selected_key in self._rows:
            self.list.select_row(self._rows[selected_key])
        elif clear_missing and isinstance(self._current, dict):
            if self._current.get("key") not in self._rows:
                self._show_item(None)
        if self._doomed:
            self._schedule_drop()

    def _retire_current(self, *, force: bool) -> None:
        existing: list[Gtk.ListBoxRow] = []
        index = 0
        while True:
            row = self.list.get_row_at_index(index)
            if row is None:
                break
            existing.append(row)
            index += 1
        for row in existing:
            if row in self._doomed:
                continue
            self._release_row(row, force=force)

    def _release_row(self, row: Gtk.ListBoxRow, *, force: bool) -> None:
        row.item = None
        row.item_key = ""
        if force and not _row_blocked(self, row):
            self.list.remove(row)
            _dispose_widget(row)
            return
        row.set_visible(False)
        row.set_sensitive(False)
        row.set_selectable(False)
        if row not in self._doomed:
            self._doomed.append(row)

    def _any_pointer_row(self) -> bool:
        index = 0
        while True:
            row = self.list.get_row_at_index(index)
            if row is None:
                return False
            if row.get_visible() and _pointer_on_row(row):
                return True
            index += 1

    def _park_list_focus(self) -> None:
        focus = self.get_focus()
        if focus is None or focus is self.list or not _widget_inside(focus, self.list):
            return
        self.list.grab_focus()

    def _schedule_drop(self) -> None:
        if not self._doomed or self._drop_idle:
            return
        self._drop_wait = True
        self._drop_idle = GLib.idle_add(self._drop_doomed)

    def _drop_doomed(self) -> bool:
        """Unparent hidden rows only after one more main-loop turn.

        The extra turn is what lets the frame clock deliver leave events
        while the row widget is still alive.
        """

        if self._drop_wait:
            self._drop_wait = False
            return GLib.SOURCE_CONTINUE
        kept: list[Gtk.ListBoxRow] = []
        for row in self._doomed:
            if row.get_parent() is None:
                _dispose_widget(row)
                continue
            if _row_blocked(self, row):
                kept.append(row)
                continue
            self.list.remove(row)
            _dispose_widget(row)
        self._doomed = kept
        if kept:
            self._drop_wait = True
            self._drop_idle = GLib.timeout_add(50, self._drop_doomed)
        else:
            self._drop_idle = 0
        return GLib.SOURCE_REMOVE

    def _fit_to_list(self) -> None:
        """Size the window to the list once. A later user resize sticks."""

        if self._user_sized or self._height_fitted:
            return
        sidebar = self._sidebar_inner_width()
        if sidebar <= 1:
            if not self._fit_correct:
                self._fit_correct = GLib.idle_add(self._correct_fit)
            return
        window_width = self.get_width()
        if not isinstance(window_width, int) or window_width < WINDOW_MIN_WIDTH:
            window_width = WINDOW_DEFAULT_WIDTH
        height = fitted_window_height(
            _natural_height(self.list, sidebar),
            self._window_chrome(sidebar, window_width),
            MIN_WINDOW_HEIGHT,
            self._usable_monitor_height(),
        )
        self._fitting_height = True
        try:
            self.set_default_size(window_width, height)
        finally:
            self._fitting_height = False
        self._height_fitted = True
        self._fit_width = sidebar
        self._saw_fitted_layout = False
        if not self._fit_correct:
            self._fit_correct = GLib.idle_add(self._correct_fit)

    def _correct_fit(self) -> bool:
        """Measure again once the sidebar has its real width.

        A guess made before allocation misses wrapped tag rows, and the
        last todo is then clipped. One correction is enough. A resize the
        user already made is left alone.
        """

        self._fit_correct = 0
        if self._user_sized:
            return GLib.SOURCE_REMOVE
        sidebar = self._sidebar_inner_width()
        if sidebar <= 1:
            self._fit_correct = GLib.idle_add(self._correct_fit)
            return GLib.SOURCE_REMOVE
        if self._height_fitted and abs(sidebar - self._fit_width) <= 16:
            return GLib.SOURCE_REMOVE
        self._height_fitted = False
        self._fit_to_list()
        return GLib.SOURCE_REMOVE

    def _sidebar_inner_width(self) -> int:
        page = self.split.get_sidebar()
        if page is not None and page.get_width() > 1:
            return int(page.get_width())
        minimum = self.split.get_min_sidebar_width()
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and minimum > 1:
            return int(minimum)
        return 300

    def _window_chrome(self, sidebar: int, window_width: int) -> int:
        """Header, controls, borders, bottom padding, and client decoration.

        Measured at the sidebar width so a wrapped tag row counts. The
        propagated toolbar height includes padding the separate pieces miss.
        """

        controls = _natural_height(self._list_controls, sidebar)
        header = _natural_height(self.titlebar, window_width)
        frame = 0
        propagated = 0
        scroll = self._list_scroll
        scroll.set_propagate_natural_height(True)
        try:
            column = _natural_height(self._sidebar_box, sidebar)
            frame = max(0, column - _natural_height(self.list, sidebar) - controls)
            propagated = _natural_height(self.toolbar, window_width)
        finally:
            scroll.set_propagate_natural_height(False)
        csd = self._csd_vertical(window_width)
        pieces = controls + header + frame + csd
        # ``propagated`` already contains the list. Keep only the chrome
        # above that list, then let the caller add the list back.
        list_h = _natural_height(self.list, sidebar)
        from_tree = max(0, propagated - list_h) + csd
        return max(pieces, from_tree)

    def _csd_vertical(self, width: int) -> int:
        extra = self.get_margin_top() + self.get_margin_bottom()
        bar = self.get_titlebar()
        if bar is not None and bar is not self.titlebar:
            extra += _natural_height(bar, width)
        return extra

    def _usable_monitor_height(self) -> int:
        display = self.get_display()
        if display is None:
            return 0
        monitor = None
        surface = self.get_surface()
        if surface is not None and hasattr(display, "get_monitor_at_surface"):
            monitor = display.get_monitor_at_surface(surface)
        if monitor is None:
            monitors = display.get_monitors()
            if monitors is not None and monitors.get_n_items() > 0:
                monitor = monitors.get_item(0)
        if monitor is None:
            return 0
        rect = monitor.get_geometry()
        work = getattr(monitor, "get_workarea", None)
        if callable(work):
            try:
                rect = work()
            except Exception:
                rect = monitor.get_geometry()
        height = getattr(rect, "height", 0)
        return int(height) if isinstance(height, int) else 0

    def _bind_size_watch(self, *_args: object) -> None:
        surface = self.get_surface()
        if surface is None or self._size_watch_id:
            return
        self._size_watch_id = surface.connect("layout", self._on_surface_layout)

    def _on_surface_layout(self, _surface: object, width: int, height: int) -> None:
        if self._fitting_height or not self._height_fitted or self._fit_correct:
            return
        size = (int(width), int(height))
        if not self._saw_fitted_layout:
            self._saw_fitted_layout = True
            self._last_layout = size
            return
        if self._last_layout != size:
            self._user_sized = True
        self._last_layout = size

    def _make_row(self, item: dict[str, Any]) -> Gtk.ListBoxRow:
        key = str(item.get("key") or "")
        undo = item.get("_undo") if isinstance(item.get("_undo"), dict) else None
        read_only = is_read_only(item) and undo is None
        outbound = self._outbound.get(key.split("/", 1)[0], False)
        check = Gtk.CheckButton()
        check.set_tooltip_text("Done")
        check.set_active(read_only)
        check.set_sensitive(can_mark_done(item, outbound))
        check.connect("toggled", self._on_check, key)
        chips = item.get("chips") if isinstance(item.get("chips"), dict) else {}
        title = Gtk.Label(label=str(item.get("title") or key), xalign=0, hexpand=True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        # One character of natural width, then the row fills the sidebar.
        # The start-timer icon keeps its own width.
        title.set_max_width_chars(1)
        top = Gtk.Box(spacing=8)
        if undo is not None and undo.get("live"):
            until = int(undo.get("until") or 0)
            button, bar = _undo_button()
            bar.set_fraction(undo_fraction(until, _now_ms(), self._undo_span))
            button.connect("clicked", lambda _button, item_key=key: self._undo(item_key))
            self._undo_bars.append((bar, until))
            top.append(button)
        elif undo is not None:
            spacer = Gtk.Box()
            spacer.set_size_request(78, 28)
            top.append(spacer)
        else:
            top.append(check)
        top.append(title)
        chip_row = Gtk.Box(spacing=6)
        bot_label = item.get("display_name")
        if isinstance(bot_label, str) and bot_label:
            chip_row.append(_chip(bot_label, "neutral"))
        due = chips.get("due")
        if isinstance(due, dict) and due.get("label"):
            chip_row.append(_chip(str(due["label"]), str(due.get("tone") or "neutral")))
        priority = chips.get("priority")
        if isinstance(priority, dict) and priority.get("label"):
            tone = str(priority.get("tone") or "neutral")
            chip_row.append(_chip(str(priority["label"]), tone))
        tags = chips.get("tags") if isinstance(chips.get("tags"), list) else []
        for tag in tags:
            if isinstance(tag, dict) and tag.get("label"):
                chip_row.append(_chip(str(tag["label"]), str(tag.get("tone") or "gray")))
        tracked = format_tracked(item.get("time_tracked_s"))
        if tracked:
            chip_row.append(_chip(tracked, "neutral"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.append(top)
        if undo is None:
            self._append_timer_control(top, item, key, read_only)
        if chip_row.get_first_child() is not None:
            chip_row.set_margin_start(28)
            box.append(chip_row)
        if read_only:
            box.add_css_class("tether-row-done")
        row = Gtk.ListBoxRow(child=box)
        row.item_key = key
        row.item = item
        return row

    def _show_item(self, item: dict[str, Any] | None) -> None:
        previous = self._current.get("key") if isinstance(self._current, dict) else None
        self._current = item
        self._link_tags.clear()
        incoming = item.get("key") if isinstance(item, dict) else None
        if previous != incoming:
            self.note_buffer.set_text("")
        self._restore_kept_note(incoming)
        if item is None:
            self.detail_title.set_label("Select a todo")
            _clear_box(self.detail_chips)
            self.buffer.set_text("")
            self.source.set_label("")
            self.done_button.set_sensitive(False)
            self._sync_done_note()
            self._sync_detail_undo("")
            self.copy_button.set_sensitive(False)
            self.copy_title_button.set_sensitive(False)
            self.copy_body_button.set_sensitive(False)
            self.ask_button.set_sensitive(False)
            self._sync_start_button(None)
            self._sync_time_editor(None)
            return
        self.detail_title.set_label(str(item.get("title") or item.get("key") or ""))
        _fill_chip_box(self.detail_chips, item.get("chips"))
        tracked = format_tracked(item.get("time_tracked_s"))
        if tracked:
            self.detail_chips.append(_chip(tracked, "neutral"))
        self._sync_time_editor(item)
        body = item.get("body") if isinstance(item.get("body"), str) else ""
        if item.get("body_format") == "markdown":
            runs = render(body)
        else:
            runs = (Run(body),) if body else ()
        apply_runs(self.buffer, runs, self._link_tags)
        self.source.set_label(source_line(item))
        key = str(item.get("key") or "")
        outbound = self._outbound.get(key.split("/", 1)[0], False)
        self.done_button.set_sensitive(can_mark_done(item, outbound))
        self._sync_done_note()
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        body = item.get("body") if isinstance(item.get("body"), str) else ""
        self.copy_title_button.set_sensitive(bool(title))
        self.copy_body_button.set_sensitive(bool(body))
        self.copy_button.set_sensitive(bool(title or body))
        self.ask_button.set_sensitive("/" in key)
        self._sync_start_button(item)
        self._sync_detail_undo(key)

    def _restore_kept_note(self, key: object) -> None:
        """Put a refused note back when this todo is the one that was kept."""

        kept = self._kept_secret_note
        if not isinstance(kept, tuple) or len(kept) != 2:
            return
        kept_key, text = kept
        if kept_key != key or not isinstance(text, str) or not text:
            return
        self.note_buffer.set_text(text)
        self._kept_secret_note = None

    def _sync_time_editor(self, item: dict[str, Any] | None) -> None:
        if (
            not isinstance(item, dict)
            or item.get("kind") != "todo"
            or not hasattr(self.client, "get_item_time")
        ):
            self.time_box.set_visible(False)
            _clear_box(self.time_records)
            return
        key = item.get("key")
        if not isinstance(key, str) or not key:
            self.time_box.set_visible(False)
            return
        try:
            payload = self.client.get_item_time(key)
        except BridgeError as exc:
            self.time_box.set_visible(True)
            self.time_entry.set_text("")
            _clear_box(self.time_records)
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self._show_time_payload(payload if isinstance(payload, dict) else {})

    def _show_time_payload(self, payload: dict[str, Any]) -> None:
        self.time_box.set_visible(True)
        total = payload.get("total_s")
        self.time_entry.set_text(format_duration(total))
        _clear_box(self.time_records)
        records = payload.get("records")
        if not isinstance(records, list):
            return
        for record in records:
            if not isinstance(record, dict) or not record.get("id"):
                continue
            row = Gtk.Box(spacing=8)
            label = Gtk.Label(label=format_time_record(record), xalign=0, hexpand=True)
            label.add_css_class("tether-source")
            delete = Gtk.Button(icon_name="user-trash-symbolic")
            delete.add_css_class("flat")
            delete.set_tooltip_text("Delete time record")
            delete.connect("clicked", self._confirm_delete_record, str(record["id"]))
            row.append(label)
            row.append(delete)
            self.time_records.append(row)

    def _set_tracked(self) -> None:
        item = self._current
        if not isinstance(item, dict) or not hasattr(self.client, "set_tracked_total"):
            return
        key = item.get("key")
        if not isinstance(key, str) or not key:
            return
        total = parse_tracked_total(self.time_entry.get_text())
        if total is None:
            self._toast("Enter a time like 1:42:00")
            return
        try:
            payload = self.client.set_tracked_total(key, total)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self._apply_tracked(payload)

    def _confirm_delete_record(self, _button: Gtk.Button, record_id: str) -> None:
        item = self._current
        if not isinstance(item, dict) or not record_id:
            return
        key = item.get("key")
        if not isinstance(key, str) or not hasattr(self.client, "delete_time_record"):
            return
        dialog = Adw.AlertDialog(
            heading="Delete this time record?",
            body="The tracked total updates to match the records that remain.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_record, key, record_id)
        self._time_dialog = dialog
        dialog.present(self)

    def _on_delete_record(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
        key: str,
        record_id: str,
    ) -> None:
        if response != "delete":
            return
        try:
            payload = self.client.delete_time_record(key, record_id)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self._apply_tracked(payload)

    def _apply_tracked(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        key = payload.get("item_key")
        total = payload.get("total_s")
        if not isinstance(key, str) or isinstance(total, bool) or not isinstance(total, int):
            self._show_time_payload(payload)
            return
        for item in self._items:
            if item.get("key") == key:
                item["time_tracked_s"] = total
        if isinstance(self._current, dict) and self._current.get("key") == key:
            self._current["time_tracked_s"] = total
        self._fill_rows(self._items)

    def _sync_detail_undo(self, key: str) -> None:
        hold = self._undo_holds.get(key) if key else None
        now = _now_ms()
        live = (
            isinstance(hold, dict)
            and not hold.get("sent")
            and int(hold.get("until") or 0) > now
        )
        via = hold.get("via") if live and isinstance(hold, dict) else ""
        if live and via not in {"done", "note"}:
            via = "done"
        self.done_stack.set_visible_child(
            self.done_stack.undo_page if via == "done" else self.done_stack.action_page
        )
        self.note_stack.set_visible_child(
            self.note_stack.undo_page if via == "note" else self.note_stack.action_page
        )
        self._done_until = int(hold["until"]) if via == "done" and isinstance(hold, dict) else 0
        self._note_until = int(hold["until"]) if via == "note" and isinstance(hold, dict) else 0
        self._done_bar.set_fraction(
            undo_fraction(self._done_until, now, self._undo_span) if self._done_until else 0
        )
        self._note_bar.set_fraction(
            undo_fraction(self._note_until, now, self._undo_span) if self._note_until else 0
        )
        self._bind_detail_bars()
        if live:
            self.done_button.set_sensitive(False)
            self.done_note_button.set_sensitive(False)
            return
        item = self._current
        if not isinstance(item, dict):
            return
        item_key = str(item.get("key") or "")
        outbound = self._outbound.get(item_key.split("/", 1)[0], False)
        self.done_button.set_sensitive(can_mark_done(item, outbound))
        self._sync_done_note()

    def _bind_detail_bars(self) -> None:
        detail = [
            (self._done_bar, self._done_until),
            (self._note_bar, self._note_until),
        ]
        rest = [
            (bar, until)
            for bar, until in self._undo_bars
            if bar is not self._done_bar and bar is not self._note_bar
        ]
        self._undo_bars = detail + rest

    def _append_timer_control(
        self,
        top: Gtk.Box,
        item: dict[str, Any],
        key: str,
        read_only: bool,
    ) -> None:
        if not hasattr(self.client, "start_timer") or read_only:
            return
        title = item.get("title") if isinstance(item.get("title"), str) else key
        if timer_item_key(self._timer) == key and key:
            top.append(Gtk.Label(label="Timing"))
            return
        play = Gtk.Button(icon_name="media-playback-start-symbolic")
        play.add_css_class("tether-play")
        play.set_hexpand(False)
        play.set_halign(Gtk.Align.CENTER)
        play.set_valign(Gtk.Align.CENTER)
        play.set_can_shrink(False)
        play.set_tooltip_text(f"Start timer: {title}")
        play.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Start timer: {title}"],
        )
        play.connect("clicked", self._on_play, key, title)
        top.append(play)

    def _on_play(self, _button: Gtk.Button, key: str, title: str) -> None:
        self._start_timer(key, title)

    def _start_current(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            return
        key = item.get("key")
        if not isinstance(key, str) or not key:
            return
        title = item.get("title") if isinstance(item.get("title"), str) else key
        if timer_item_key(self._timer) == key:
            self._stop_owned_timer()
            return
        self._start_timer(key, title)

    def _stop_owned_timer(self) -> None:
        if not hasattr(self.client, "stop_timer"):
            return
        try:
            updated = self.client.stop_timer()
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        if isinstance(updated, dict) and updated.get("state"):
            self._apply_timer_result(updated)
            return
        self._timer = {"state": "idle"}
        self._show_page_list()
        self._sync_timer_strip()
        self._sync_start_button(self._current)
        self.refresh()

    def _start_timer(self, key: str, title: str) -> None:
        if not hasattr(self.client, "start_timer"):
            return
        state = self._timer.get("state") if isinstance(self._timer, dict) else ""
        holding = state in {"running", "paused", "stopped"}
        current = timer_item_key(self._timer) if holding else ""
        if holding and current != key:
            running = self._timer.get("item_title")
            shown = running if isinstance(running, str) and running else "Timer"
            self._switch_ask = {
                "key": key,
                "title": shown,
                "next": title,
                "discard": state == "stopped",
            }
            self._sync_switch()
            return
        if holding:
            return
        self._switch_ask = None
        self._sync_switch()
        try:
            started = self.client.start_timer(key)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        if isinstance(started, dict) and started:
            self._timer = started
        self._show_page_list()
        self._sync_timer_strip()
        self.refresh()

    def _confirm_switch(self) -> None:
        ask = self._switch_ask
        if not ask or not hasattr(self.client, "start_timer"):
            return
        key = ask.get("key") or ""
        state = self._timer.get("state")
        tied = bool(timer_item_key(self._timer))
        self._switch_ask = None
        self._sync_switch()
        try:
            if state == "stopped":
                if not hasattr(self.client, "dismiss_timer"):
                    return
                self.client.dismiss_timer()
            else:
                if not hasattr(self.client, "stop_timer"):
                    return
                self.client.stop_timer()
                if not tied and hasattr(self.client, "dismiss_timer"):
                    self.client.dismiss_timer()
            started = self.client.start_timer(key)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            self._request_timer()
            return
        if isinstance(started, dict) and started:
            self._timer = started
        self.refresh()

    def _cancel_switch(self) -> None:
        self._switch_ask = None
        self._sync_switch()

    def _sync_switch(self) -> None:
        ask = self._switch_ask
        if not ask:
            self.switch_box.set_visible(False)
            return
        if ask.get("discard"):
            self.switch_label.set_label("Discard the stopped time and start this one?")
        else:
            title = ask.get("title") or "Timer"
            self.switch_label.set_label(f"Stop {title} and start this one?")
        self.switch_box.set_visible(True)

    def _sync_start_button(self, item: dict[str, Any] | None) -> None:
        offered = (
            hasattr(self.client, "start_timer") and item is not None and not is_read_only(item)
        )
        self.start_button.set_visible(True)
        self.attach_button.set_visible(True)
        if not offered or item is None:
            self.start_button.set_label("Start timer")
            self.start_button.set_sensitive(False)
        else:
            key = str(item.get("key") or "")
            if timer_item_key(self._timer) == key and key:
                self.start_button.set_label("Stop timer")
                self.start_button.set_sensitive(True)
            else:
                self.start_button.set_label("Start timer")
                self.start_button.set_sensitive(True)
        self.attach_button.set_sensitive(self._can_attach(item))

    def _can_attach(self, item: dict[str, Any] | None) -> bool:
        if item is None or not hasattr(self.client, "attach_timer") or is_read_only(item):
            return False
        state = self._timer.get("state")
        if state == "stopped":
            return True
        return state in {"running", "paused"} and not timer_item_key(self._timer)

    def _set_editing_start(self, editing: bool) -> None:
        self._editing_start = editing
        state = self._timer.get("state")
        self.edit_start_box.set_visible(
            editing and state in {"running", "paused"} and hasattr(self.client, "adjust_start")
        )

    def _sync_timer_strip(self) -> None:
        timer = self._timer if isinstance(self._timer, dict) else {}
        state = timer.get("state")
        has_timer = hasattr(self.client, "get_timer") or hasattr(self.client, "load_timer")
        if state not in {"running", "paused", "stopped"} or not has_timer:
            self._editing_start = False
            self.timer_box.set_visible(False)
            self.edit_start_box.set_visible(False)
            return
        clock = format_top_bar(_display_elapsed(timer))
        title = timer.get("item_title") if isinstance(timer.get("item_title"), str) else ""
        if state == "stopped":
            text = f"Stopped, unassigned · {clock}"
        elif state == "paused":
            text = f"Paused · {clock}"
        else:
            text = f"Timer running · {clock}"
        if title:
            text = f"{text} · {title}"
        self.timer_label.set_label(text)
        self.timer_box.set_visible(True)
        _clear_box(self.timer_actions)
        if state == "stopped" and hasattr(self.client, "dismiss_timer"):
            dismiss = Gtk.Button(label="Dismiss")
            dismiss.connect("clicked", lambda _button: self._dismiss_timer())
            self.timer_actions.append(dismiss)
        elif state in {"running", "paused"} and hasattr(self.client, "adjust_start"):
            edit = Gtk.Button(label="Edit start")
            edit.connect("clicked", lambda _button: self._set_editing_start(True))
            self.timer_actions.append(edit)
        if state not in {"running", "paused"}:
            self._editing_start = False
        self._set_editing_start(self._editing_start)

    def _on_adjust_start(self, _button: Gtk.Button, delta: int) -> None:
        if not hasattr(self.client, "adjust_start"):
            return
        try:
            updated = self.client.adjust_start(int(delta))
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self._apply_timer_result(updated)

    def _on_set_start(self, _widget: Gtk.Widget | None = None) -> None:
        if not hasattr(self.client, "set_start"):
            return
        started = parse_start_clock(self.start_entry.get_text())
        if started is None:
            self._toast("Use HH:MM")
            return
        try:
            updated = self.client.set_start(started)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self.start_entry.set_text("")
        self._apply_timer_result(updated)

    def _attach_current(self) -> None:
        item = self._current
        if not isinstance(item, dict) or not self._can_attach(item):
            return
        key = item.get("key")
        if not isinstance(key, str) or not key:
            return
        try:
            updated = self.client.attach_timer(key)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        if not isinstance(updated, dict) or not updated.get("state"):
            self._request_timer()
            return
        self._apply_timer_result(updated)

    def _dismiss_timer(self) -> None:
        if not hasattr(self.client, "dismiss_timer"):
            return
        try:
            updated = self.client.dismiss_timer()
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc, fallback="Could not save the timer"))
            return
        self._apply_timer_result(updated)

    def _apply_timer_result(self, updated: object) -> None:
        if isinstance(updated, dict) and updated:
            self._timer = updated
        self._editing_start = False
        self._show_page_list()
        self._sync_timer_strip()
        self._sync_start_button(self._current)

    def _request_timer(self) -> None:
        self._timer_generation += 1
        generation = self._timer_generation
        if hasattr(self.client, "load_timer"):

            def _done(
                timer: dict[str, Any],
                error: BridgeError | None,
                generation: int = generation,
            ) -> None:
                if generation != self._timer_generation:
                    return
                self._on_timer(timer, error)

            self.client.load_timer(_done)
            return
        if not hasattr(self.client, "get_timer"):
            return
        try:
            timer = self.client.get_timer()
        except BridgeError as exc:
            self._on_timer({}, exc)
            return
        self._on_timer(timer if isinstance(timer, dict) else {}, None)

    def _on_timer(self, timer: dict[str, Any], error: BridgeError | None) -> None:
        if error is not None:
            return
        self._timer = timer if isinstance(timer, dict) else {"state": "idle"}
        self._show_page_list()
        self._sync_switch()
        self._sync_timer_strip()
        self._sync_start_button(self._current)

    def _done_current(self) -> None:
        item = self._current
        if item is None:
            return
        key = item.get("key")
        if not isinstance(key, str):
            return
        outbound = self._outbound.get(key.split("/", 1)[0], False)
        if can_mark_done(item, outbound):
            self._mark_done(key)

    def _note_text(self) -> str:
        start, end = self.note_buffer.get_bounds()
        return self.note_buffer.get_text(start, end, True).strip()

    def _sync_done_note(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            self.done_note_button.set_sensitive(False)
            return
        if (
            self.done_stack.get_visible_child() is self.done_stack.undo_page
            or self.note_stack.get_visible_child() is self.note_stack.undo_page
        ):
            self.done_note_button.set_sensitive(False)
            return
        key = str(item.get("key") or "")
        outbound = self._outbound.get(key.split("/", 1)[0], False)
        ready = bool(self._note_text()) and can_mark_done(item, outbound)
        self.done_note_button.set_sensitive(ready)

    def _done_with_note(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            return
        key = item.get("key")
        if not isinstance(key, str):
            return
        note = self._note_text()
        if not note:
            return
        if len(note) > 500:
            self._toast("Note must be 1 to 500 characters")
            return
        outbound = self._outbound.get(key.split("/", 1)[0], False)
        if not can_mark_done(item, outbound):
            return
        if looks_like_secret(note):
            self._toast(SECRET_NOTE_MESSAGE)
            return
        self._mark_done(key, note)
        self.note_buffer.set_text("")

    def _undo_window_ms(self) -> int:
        """The shared undo length, from settings, in milliseconds."""

        from tetherbot.ui_settings import resolve_ui_settings

        return resolve_ui_settings(None).undo_seconds * 1000

    def _mark_done(self, key: str, note: str = "") -> None:
        index = 0
        snapshot: dict[str, Any] | None = None
        for item in self._items:
            if item.get("key") == key:
                snapshot = dict(item)
                break
        pin_keys = self._pin_keys()
        shown = merge_undo_items(
            self._items,
            self._undo_holds,
            _now_ms(),
            pin_expired=pin_keys is None or bool(pin_keys),
            pin_keys=pin_keys,
            window_ms=self._undo_span,
        )
        found = False
        for position, item in enumerate(shown):
            if item.get("key") == key:
                index = position
                found = True
                break
        if snapshot is None:
            snapshot = {"key": key, "title": key, "status": "open", "kind": "todo"}
        shown_after = ""
        if found and index + 1 < len(shown):
            neighbor = shown[index + 1].get("key")
            if isinstance(neighbor, str):
                shown_after = neighbor
        self._undo_span = self._undo_window_ms()
        self._undo_holds = note_done(
            self._undo_holds,
            key,
            snapshot,
            index,
            shown_after,
            _now_ms(),
            self._undo_span,
        )
        if note:
            self._undo_holds[key]["note"] = note
            self._undo_holds[key]["via"] = "note"
        else:
            self._undo_holds[key]["via"] = "done"
        self._arm_undo()
        self._fill_rows(self._items)
        self._sync_open_undo()

    def _undo_current(self) -> None:
        item = self._current
        key = item.get("key") if isinstance(item, dict) else ""
        if isinstance(key, str) and key:
            self._undo(key)

    def _undo(self, key: str) -> None:
        hold = self._undo_holds.pop(key, None)
        self._arm_undo()
        if hold is not None and hold.get("sent"):
            try:
                result = self.client.undo(key)
            except BridgeError as exc:
                self._toast(friendly_bridge_message(exc))
                return
            if result.get("result") == "dropped":
                self._toast("Brought back. Nothing was sent.")
            else:
                self._toast("Asked the bot to reopen it.")
        else:
            self._toast("Brought back. Nothing was sent.")
        self._wanted = key
        self.refresh()
        if not hasattr(self.client, "load_list"):
            self._focus_key(key)

    def _ask_current(self) -> None:
        item = self._current
        if item is None or not isinstance(item.get("key"), str):
            return
        try:
            self.client.send_note(item["key"])
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        self._toast("Sent a note about this item")

    def _copy_title(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            return
        text = copy_title(item)
        if not text:
            return
        self.get_clipboard().set(text)
        self._toast("Copied title")

    def _copy_body(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            return
        text = copy_body(item)
        if not text:
            return
        self.get_clipboard().set(text)
        self._toast("Copied body")

    def _copy_current(self) -> None:
        item = self._current
        if not isinstance(item, dict):
            return
        text = copy_todo(item)
        if not text:
            return
        self.get_clipboard().set(text)
        self._toast("Copied")

    def _toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))

    def _on_window_close(self, _window: Gtk.Window) -> bool:
        self._flush_due(True, rebuild=False)
        self._cancel_after_send()
        self._undo_holds.clear()
        self.drop_undo_timers()
        return False

    def drop_undo_timers(self) -> None:
        """Stop undo ticks. Safe to call more than once."""

        source = self._undo_source
        paint = self._undo_paint
        self._undo_source = 0
        self._undo_paint = 0
        if source:
            GLib.source_remove(source)
        if paint:
            GLib.source_remove(paint)

    def _set_list_hover(self, hovered: bool) -> None:
        self._list_hovered = hovered
        if not hovered:
            self._drop_expired_undos()

    def _arm_undo(self) -> None:
        if self._undo_source:
            GLib.source_remove(self._undo_source)
            self._undo_source = 0
        now = _now_ms()
        soonest = 0
        for hold in self._undo_holds.values():
            remain = int(hold["until"]) - now
            if remain <= 0:
                continue
            if soonest == 0 or remain < soonest:
                soonest = remain
        if soonest > 0:
            self._undo_source = GLib.timeout_add(max(1, soonest), self._on_undo_due)
        self._arm_undo_paint()

    def _on_undo_due(self) -> bool:
        self._undo_source = 0
        self._flush_due(False)
        return GLib.SOURCE_REMOVE

    def _flush_due(self, force: bool, *, rebuild: bool = True) -> None:
        """Send every cleared row whose shared window has ended, as one queue batch.

        ``mark_done`` is a blocking bus call. Rebuilding the list in this same
        turn destroys the row the pointer is on before GTK can deliver the
        crossing events queued during the call, which crashes in
        ``gtk_synthesize_crossing_events``. The list update waits for an idle.
        A failed send is not retried here: the row stays until that idle, then
        the open item comes back unless the bridge already accepted the action.
        """

        keys = due_undo_keys(self._undo_holds, _now_ms(), force=force)
        needs_ui = False
        for key in keys:
            hold = self._undo_holds.get(key)
            if hold is None or hold.get("sent"):
                continue
            if hold.get("failed"):
                needs_ui = True
                self._after_send_refresh = True
                continue
            note = hold.get("note")
            try:
                if isinstance(note, str) and note.strip():
                    self.client.mark_done(key, note.strip())
                else:
                    self.client.mark_done(key)
            except BridgeError as exc:
                raw = str(exc)
                self._toast(friendly_bridge_message(raw))
                if "looks like a secret" in raw.casefold():
                    self._undo_holds.pop(key, None)
                    restored = note.strip() if isinstance(note, str) else ""
                    if restored:
                        self._kept_secret_note = (key, restored)
                        current = (
                            self._current.get("key") if isinstance(self._current, dict) else None
                        )
                        if current == key:
                            self.note_buffer.set_text(restored)
                    needs_ui = True
                    self._after_send_refresh = True
                    continue
                hold["failed"] = True
                needs_ui = True
                self._after_send_refresh = True
                continue
            hold["sent"] = True
            hold["until"] = _now_ms()
            needs_ui = True
            self._after_send_refresh = True
        if rebuild and needs_ui:
            self._schedule_after_send()

    def _schedule_after_send(self) -> None:
        if self._after_send_idle:
            return
        self._after_send_idle = GLib.idle_add(self._after_send)

    def _cancel_after_send(self) -> None:
        source = self._after_send_idle
        self._after_send_idle = 0
        if source:
            GLib.source_remove(source)

    def _after_send(self) -> bool:
        """One list update after a send attempt.

        A failed send waits while the pointer is on that row. A send that
        landed still rebuilds here, and the install path hides a hovered row
        instead of freeing it.
        """

        self._after_send_idle = 0
        if self._failed_row_under_pointer():
            self._after_send_idle = GLib.timeout_add(50, self._after_send)
            return GLib.SOURCE_REMOVE
        refresh = self._after_send_refresh
        self._after_send_refresh = False
        if refresh:
            self.refresh()
        self._settle_holds(fill=not refresh)
        return GLib.SOURCE_REMOVE

    def _list_hot(self) -> bool:
        return bool(
            self._list_hovered or self._guard_rows or self._doomed or self._any_pointer_row()
        )

    def _pin_keys(self) -> set[str] | None:
        """Expired rows to keep so the pointer's row does not jump.

        ``None`` means the pointer is on the list but not on one row, so
        every expired unsent row stays. An empty set pins nothing.
        """

        if not self._list_hovered:
            return set()
        pointed: set[str] = set()
        index = 0
        while True:
            row = self.list.get_row_at_index(index)
            if row is None:
                break
            index += 1
            if not row.get_visible() or not _pointer_on_row(row):
                continue
            key = getattr(row, "item_key", "")
            if isinstance(key, str) and key:
                pointed.add(key)
        if pointed:
            return pointed
        return None

    def _failed_row_under_pointer(self) -> bool:
        """True when a failed send's row is the one under the pointer."""

        if not self._list_hot():
            return False
        pin = self._pin_keys()
        now = _now_ms()
        for key, hold in self._undo_holds.items():
            if hold.get("sent"):
                continue
            pending = bool(hold.get("failed")) or int(hold.get("until") or 0) <= now
            if pending and (pin is None or key in pin):
                return True
        return False

    def _settle_holds(self, *, fill: bool = True) -> None:
        now = _now_ms()
        pin = self._pin_keys()
        before = set(self._undo_holds)
        kept: dict[str, dict[str, Any]] = {}
        for key, hold in self._undo_holds.items():
            if hold.get("sent"):
                continue
            if int(hold.get("until") or 0) > now:
                kept[key] = hold
                continue
            if self._list_hovered and (pin is None or key in pin):
                kept[key] = hold
        self._undo_holds = kept
        if fill and set(self._undo_holds) != before and self._page != "bots":
            self._fill_rows(self._items)
        self._sync_open_undo()
        self._arm_undo()

    def _drop_expired_undos(self) -> None:
        self._flush_due(False)
        if self._after_send_idle:
            return
        self._settle_holds()

    def _arm_undo_paint(self) -> None:
        if self._undo_holds and not self._undo_paint:
            self._undo_paint = GLib.timeout_add(100, self._on_undo_paint)

    def _on_undo_paint(self) -> bool:
        if not self._undo_holds:
            self._undo_paint = 0
            return GLib.SOURCE_REMOVE
        self._paint_undo_bars()
        now = _now_ms()
        due = bool(due_undo_keys(self._undo_holds, now))
        stale = any(
            hold.get("sent") or int(hold.get("until") or 0) <= now
            for hold in self._undo_holds.values()
        )
        if due or (stale and not self._list_hovered):
            self._drop_expired_undos()
        if not self._undo_holds:
            self._undo_paint = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _paint_undo_bars(self) -> None:
        now = _now_ms()
        for bar, until in self._undo_bars:
            bar.set_fraction(undo_fraction(until, now, self._undo_span))

    def _sync_open_undo(self) -> None:
        item = self._current
        key = item.get("key") if isinstance(item, dict) else ""
        if isinstance(key, str):
            self._sync_detail_undo(key)

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        if self._filling:
            return
        self._query = entry.get_text()
        self.refresh()

    def _on_view(self, button: Gtk.ToggleButton) -> None:
        if self._filling or not button.get_active():
            return
        self._view = button.view_name
        self.refresh()

    def _on_tag(self, button: Gtk.ToggleButton, tag: str) -> None:
        if self._filling:
            return
        if button.get_active():
            self._tags_on.add(tag)
        else:
            self._tags_on.discard(tag)
        self._clear.set_sensitive(bool(self._tags_on))
        self.refresh()

    def _on_clear_tags(self, _button: Gtk.Button) -> None:
        self._tags_on.clear()
        self.refresh()

    def _on_sort(self, drop: Gtk.DropDown, _pspec: Any) -> None:
        if self._filling:
            return
        selected = drop.get_selected()
        if 0 <= selected < len(SORTS):
            self._sort = SORTS[selected]
            self.refresh()

    def _on_show_done(self, switch: Gtk.Switch, _pspec: Any) -> None:
        if self._filling:
            return
        self._show_done = bool(switch.get_active())
        self.refresh()

    def _on_check(self, button: Gtk.CheckButton, key: str) -> None:
        if self._filling or not button.get_active():
            return
        self._guard_rows = True
        try:
            self._mark_done(key)
        finally:
            self._guard_rows = False

    def _on_row_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self._filling or self._page in {"bots", "clipboard"}:
            return
        if row is None:
            return
        item = getattr(row, "item", None)
        key = item.get("key") if isinstance(item, dict) else getattr(row, "item_key", "")
        if isinstance(key, str) and key:
            self._wanted = key
        self._show_item(item)

    def _on_row_activated(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if self._page == "clipboard":
            self._preview_clipboard(row)
            return
        if self._page == "bots":
            bot_id = getattr(row, "bot_id", "")
            if isinstance(bot_id, str) and bot_id:
                self._bot_filter = {bot_id}
                self._set_page("todos")
                self.refresh()
            return
        self._show_item(getattr(row, "item", None))
        if self.split.get_collapsed():
            self.split.set_show_content(True)

    def _on_bot_search(self, entry: Gtk.SearchEntry) -> None:
        self._bot_query = entry.get_text()
        if self._page == "bots":
            self._fill_bot_rows()

    def _on_page(self, button: Gtk.ToggleButton, page: str) -> None:
        if self._filling or not button.get_active():
            return
        self._set_page(page)

    def _on_bot_chip(self, button: Gtk.ToggleButton, bot_id: str) -> None:
        if self._filling:
            return
        if button.get_active():
            self._bot_filter.add(bot_id)
        else:
            self._bot_filter.discard(bot_id)
        self.refresh()

    def _set_page(self, page: str) -> None:
        self._page = page if page in {"todos", "bots", "clipboard"} else "todos"
        if self._page == "clipboard":
            self._clip_search_ready = False
        self._todo_controls.set_visible(self._page == "todos")
        self.bot_search.set_visible(self._page == "bots")
        self._clip_controls.set_visible(self._page == "clipboard")
        self._sync_pages()
        self._show_page_list()

    def _show_page_list(self) -> None:
        if self._page == "bots":
            self._fill_bot_rows()
        elif self._page == "clipboard":
            self._reload_clipboard()
        else:
            self._fill_rows(self._items)

    def _fill_bot_chips(self) -> None:
        self._filling = True
        while (child := self.bot_box.get_first_child()) is not None:
            self.bot_box.remove(child)
        shown = [bot for bot in self._known_bots if isinstance(bot.get("name"), str)]
        self.bot_box.set_visible(len(shown) > 1)
        for bot in shown:
            ident = str(bot.get("name"))
            label = bot.get("display_name")
            text = label if isinstance(label, str) and label else ident
            button = Gtk.ToggleButton(label=text)
            button.add_css_class("tether-chip")
            button.set_active(ident in self._bot_filter)
            button.connect("toggled", self._on_bot_chip, ident)
            self.bot_box.append(button)
        self._filling = False

    def _fill_bot_rows(self) -> None:
        query = self._bot_query.casefold().strip()
        now = int(time.time())
        rows: list[Gtk.ListBoxRow] = []
        for bot in self._known_bots:
            ident = bot.get("name")
            if not isinstance(ident, str) or not ident:
                continue
            label = bot.get("display_name")
            text = label if isinstance(label, str) and label else ident
            if query and query not in text.casefold() and query not in ident.casefold():
                continue
            rows.append(self._make_bot_row(bot, text, now))
        self._install_rows(rows, "", clear_missing=False)

    def _on_clipboard_changed(self) -> None:
        if self._page == "clipboard":
            self._reload_clipboard()

    def _on_clip_search(self, entry: Gtk.SearchEntry) -> None:
        self._clip_query = entry.get_text()
        if self._page == "clipboard":
            self._fill_clipboard_rows()

    def _reload_clipboard(self) -> None:
        self._clip_gen += 1
        token = self._clip_gen
        if hasattr(self.client, "load_clipboard"):
            self.client.load_clipboard(
                lambda entries, error, token=token: self._on_clipboard_loaded(
                    entries, error, token
                )
            )
            return
        if hasattr(self.client, "get_clipboard"):
            try:
                self._clip_entries = self.client.get_clipboard()
            except BridgeError as exc:
                self.banner.set_title(friendly_bridge_message(exc))
                self.banner.set_revealed(True)
                self._clip_entries = []
        self._fill_clipboard_rows()
        self._apply_clip_pending(loaded=True)

    def _on_clipboard_loaded(
        self,
        entries: list[dict[str, Any]],
        error: BridgeError | None,
        token: int | None = None,
    ) -> None:
        if token is not None and token != self._clip_gen:
            return
        if self._page != "clipboard":
            return
        if error is not None:
            self.banner.set_title(friendly_bridge_message(error))
            self.banner.set_revealed(True)
            self._clip_entries = []
        else:
            self.banner.set_revealed(False)
            self._clip_entries = entries
        self._fill_clipboard_rows()
        self._apply_clip_pending(loaded=True)

    def _clip_heading_row(self, title: str) -> Gtk.ListBoxRow:
        label = Gtk.Label(label=title, xalign=0)
        label.set_margin_top(8)
        label.set_margin_bottom(2)
        label.set_margin_start(8)
        label.set_margin_end(8)
        row = Gtk.ListBoxRow(child=label)
        row.set_selectable(False)
        row.set_activatable(False)
        row.clip_heading = title
        return row

    def _clip_separator_row(self) -> Gtk.ListBoxRow:
        line = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        line.set_hexpand(True)
        line.set_margin_top(6)
        line.set_margin_bottom(6)
        row = Gtk.ListBoxRow(child=line)
        row.set_selectable(False)
        row.set_activatable(False)
        row.clip_separator = True
        return row

    def _clip_note_row(self, text: str) -> Gtk.ListBoxRow:
        empty = Gtk.Label(label=text, xalign=0)
        empty.add_css_class("dim-label")
        empty.set_margin_top(8)
        empty.set_margin_bottom(8)
        empty.set_margin_start(8)
        row = Gtk.ListBoxRow(child=empty)
        row.set_selectable(False)
        row.set_activatable(False)
        row.clip_note = text
        return row

    def _fill_clipboard_rows(self) -> None:
        self._sync_clip_tags()
        query = self._clip_query.casefold().strip()
        tag_filter = self._clip_tag
        pinned_rows: list[Gtk.ListBoxRow] = []
        regular_rows: list[Gtk.ListBoxRow] = []
        for entry in self._clip_entries:
            text = entry.get("text")
            ident = entry.get("id")
            masked = entry.get("masked") is True
            if not isinstance(ident, str) or not isinstance(entry, dict):
                continue
            if not isinstance(text, str):
                text = ""
            is_image = entry.get("kind") == "image"
            if not masked and not text and not is_image:
                continue
            names = _clip_tag_names(entry)
            if tag_filter and tag_filter not in names:
                continue
            if query:
                tag_hit = any(query in name.casefold() for name in names)
                if masked:
                    if not tag_hit and query not in "hidden password":
                        continue
                elif is_image:
                    if not tag_hit and not _image_query_hit(entry, query):
                        continue
                elif not tag_hit and query not in text.casefold():
                    continue
            row = self._make_clip_row(entry, text, masked)
            if entry.get("pinned") is True:
                pinned_rows.append(row)
            else:
                regular_rows.append(row)
        rows: list[Gtk.ListBoxRow] = [
            self._clip_heading_row("Pinned"),
            *pinned_rows,
            self._clip_separator_row(),
            self._clip_heading_row("Unpinned"),
        ]
        if not pinned_rows and not regular_rows:
            note = "No matches" if query or tag_filter else "Nothing copied yet"
            rows.append(self._clip_note_row(note))
        else:
            rows.extend(regular_rows)
        self._install_rows(rows, "", clear_missing=False)

    def _sync_clip_tags(self) -> None:
        names: list[str] = []
        for entry in self._clip_entries:
            for name in _clip_tag_names(entry):
                if name not in names:
                    names.append(name)
        labels = ["All tags", *names]
        current = self._clip_tag if self._clip_tag in names else ""
        self._clip_tag = current
        wanted = 0 if not current else labels.index(current)
        model = self.clip_tag.get_model()
        same = (
            model is not None
            and model.get_n_items() == len(labels)
            and all(model.get_string(index) == labels[index] for index in range(len(labels)))
        )
        if same and self.clip_tag.get_selected() == wanted:
            return
        self._clip_tag_guard = True
        try:
            if not same:
                self.clip_tag.set_model(Gtk.StringList.new(labels))
            if self.clip_tag.get_selected() != wanted:
                self.clip_tag.set_selected(wanted)
        finally:
            self._clip_tag_guard = False

    def _on_clip_tag(self, drop: Gtk.DropDown, _pspec: Any) -> None:
        if self._clip_tag_guard or self._filling:
            return
        item = drop.get_selected_item()
        raw = item.get_string() if item is not None and hasattr(item, "get_string") else ""
        chosen = "" if not isinstance(raw, str) or raw == "All tags" else raw
        if chosen == self._clip_tag:
            return
        self._clip_tag = chosen
        self._fill_clipboard_rows()

    def _make_clip_row(self, entry: dict[str, Any], text: str, masked: bool) -> Gtk.ListBoxRow:
        ident = str(entry.get("id") or "")
        pinned = entry.get("pinned") is True
        is_image = entry.get("kind") == "image"
        if is_image:
            mime = entry.get("mime") if isinstance(entry.get("mime"), str) else ""
            size = entry.get("size") if isinstance(entry.get("size"), int) else 0
            preview = image_label(mime, size)
        elif masked:
            preview = "Hidden password"
        else:
            preview = list_preview(text) or "Empty"
        label = Gtk.Label(label=preview, xalign=0, hexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_wrap(False)
        label.set_valign(Gtk.Align.CENTER)
        label.set_halign(Gtk.Align.START)
        dots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dots.set_valign(Gtk.Align.CENTER)
        for tag in entry.get("tags") or []:
            if not isinstance(tag, dict) or not isinstance(tag.get("name"), str):
                continue
            color = tag.get("color") if isinstance(tag.get("color"), str) else "gray"
            dots.append(_clip_dot(tag["name"], color))
        text_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        text_box.add_css_class("tether-clip-text")
        text_box.set_hexpand(True)
        text_box.set_size_request(260, -1)
        text_box.set_valign(Gtk.Align.CENTER)
        if is_image:
            thumb = _clip_picture(entry)
            if thumb is not None:
                text_box.append(thumb)
        text_box.append(label)
        if dots.get_first_child() is not None:
            text_box.append(dots)
        pin_tip = "Unpin" if pinned else "Pin"
        pin = _clip_icon("view-pin-symbolic", pin_tip)
        pin.connect("clicked", self._on_pin_clip, entry)
        tag_tip = "Hidden passwords are not tagged" if masked else "Tag"
        tag_button = _clip_icon("tetherbot-tag-symbolic", tag_tip, not masked)
        tag_button.connect("clicked", self._on_tag_clip, entry)
        edit_tip = "Images are not edited" if is_image else "Edit"
        edit = _clip_icon("document-edit-symbolic", edit_tip, not masked and not is_image)
        edit.connect("clicked", self._on_edit_clip, entry)
        copy = _clip_icon("edit-copy-symbolic", "Copy")
        copy.connect("clicked", self._on_copy_clip, entry)
        template = self._search_template()
        if is_image:
            web_tip = "Images are not searched"
            web_on = False
        elif masked:
            web_tip = "Hidden passwords are not searched"
            web_on = False
        elif self._clip_search_kind == "fallback":
            web_tip = "Uses the search fallback from Settings"
            web_on = template is not None
        elif template is None:
            web_tip = "No default search engine is set"
            web_on = False
        else:
            web_tip = "Search the web"
            web_on = True
        web = _clip_icon(
            "system-search-symbolic",
            web_tip,
            web_on,
        )
        web.connect("clicked", self._on_search_clip, entry)
        if is_image:
            send_blocked = "Images are not sent"
        elif masked:
            send_blocked = "Hidden passwords are not sent"
        else:
            send_blocked = ""
        sendable = not send_blocked

        def send_button(icon_name: str, name: str, action: str) -> Gtk.Button:
            button = _clip_icon(icon_name, send_blocked or name, sendable)
            if action == "clip-todo-context":
                button.connect("clicked", self._on_context_clip, entry, label)
            else:
                button.connect("clicked", self._on_send_clip, entry, action, label)
            return button

        make_todo = send_button("tetherbot-check-symbolic", "Make a todo", "clip-todo")
        make_context = send_button(
            "tetherbot-square-check-symbolic",
            "Make a todo with context",
            "clip-todo-context",
        )
        tell_more = send_button("tetherbot-circle-help-symbolic", "Tell me more", "clip-ask")
        delete = _clip_icon("edit-delete-symbolic", "Delete")
        delete.connect("clicked", self._on_delete_clip, ident)
        actions = _clip_actions(
            [edit, pin, tag_button, copy, web, make_todo, make_context, tell_more, delete]
        )
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        line.set_margin_top(4)
        line.set_margin_bottom(4)
        line.set_margin_start(8)
        line.set_margin_end(4)
        line.append(text_box)
        line.append(actions)
        row = Gtk.ListBoxRow(child=line)
        row.clip_id = ident
        row.clip_text = text
        row.clip_masked = masked
        row.clip_entry = entry
        row.clip_kind = "image" if is_image else "text"
        return row

    def _on_send_clip(
        self,
        _button: Gtk.Button,
        entry: dict[str, Any],
        action: str,
        label: Gtk.Label,
    ) -> None:
        self._send_clip_now(entry, action, label, "primary")

    def _on_context_clip(
        self,
        button: Gtk.Button,
        entry: dict[str, Any],
        label: Gtk.Label,
    ) -> None:
        if entry.get("kind") == "image" or entry.get("masked") is True:
            return
        self._prompt_clip_context(button, entry, label)

    def _send_clip_now(
        self,
        entry: dict[str, Any],
        action: str,
        label: Gtk.Label,
        target_bot: str,
    ) -> None:
        if entry.get("kind") == "image" or entry.get("masked") is True:
            return
        ident = entry.get("id")
        if not isinstance(ident, str) or not hasattr(self.client, "send_clipboard"):
            self._flash_clip_label(label, "Not sent: Bridge not running")
            return
        bot = target_bot if isinstance(target_bot, str) and target_bot else "primary"
        try:
            result = self.client.send_clipboard(ident, action, bot)
        except BridgeError as exc:
            self._flash_clip_label(label, clip_send_message(exc))
            return
        if result == "sent":
            self._flash_clip_label(label, "Sent")
            return
        self._flash_clip_label(label, "Not sent")

    def _context_effort(self) -> str:
        try:
            effort = load_ui_settings().context_effort
        except Exception:
            return "low"
        if effort in {"low", "medium", "high"}:
            return effort
        return "low"

    def _context_bots(self) -> list[str]:
        """Primary, then bot ids already known from the feed."""

        names: list[str] = []
        seen: set[str] = set()

        def add(name: object) -> None:
            if _bot_id(name) and name not in seen:
                seen.add(str(name))
                names.append(str(name))

        add("primary")
        for bot in self._known_bots:
            if isinstance(bot, dict):
                add(bot.get("name"))
        if hasattr(self.client, "bots"):
            try:
                fresh = self.client.bots()
            except Exception:
                fresh = []
            if isinstance(fresh, list):
                for bot in fresh:
                    if isinstance(bot, dict):
                        add(bot.get("name"))
        for item in self._items:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if isinstance(source, dict):
                add(source.get("bot"))
            key = item.get("key")
            if isinstance(key, str) and "/" in key:
                add(key.split("/", 1)[0])
        rest = sorted(name for name in names if name != "primary")
        return ["primary", *rest]

    def _show_clip_popover(self, parent: object, child: Gtk.Widget) -> Gtk.Popover | None:
        if not isinstance(parent, Gtk.Widget):
            return None
        self._popover_reload = False
        self._close_clip_popover()
        popover = Gtk.Popover()
        popover.set_autohide(True)
        popover.set_child(child)
        popover.set_parent(parent)
        popover.connect("closed", self._on_clip_popover_closed)
        self._clip_popover = popover
        popover.popup()
        return popover

    def _on_clip_popover_closed(self, popover: Gtk.Popover) -> None:
        reload = self._popover_reload
        self._popover_reload = False
        if self._clip_popover is popover:
            self._clip_popover = None
        if self._clip_context_dialog is popover:
            self._clip_context_dialog = None

        def _drop() -> bool:
            if popover.get_parent() is not None:
                popover.unparent()
            if reload:
                self._reload_clip_now()
            return False

        GLib.idle_add(_drop)

    def _close_clip_popover(self) -> None:
        popover = self._clip_popover
        if popover is None:
            return
        if popover.get_visible():
            popover.popdown()
            return
        self._on_clip_popover_closed(popover)

    def _prompt_clip_context(
        self,
        parent: object,
        entry: dict[str, Any],
        label: Gtk.Label,
    ) -> None:
        effort = self._context_effort()
        box = _build_context_editor(
            effort,
            self._context_bots(),
            lambda target: self._send_context(entry, label, target),
            self._close_clip_popover,
        )
        popover = self._show_clip_popover(parent, box)
        if popover is None:
            return
        popover.effort_level = box.effort_level
        popover.bot_buttons = box.bot_buttons
        popover.send_button = box.send_button
        popover.cancel_button = box.cancel_button
        self._clip_context_dialog = popover

    def _send_context(self, entry: dict[str, Any], label: Gtk.Label, target: str) -> None:
        self._send_clip_now(entry, "clip-todo-context", label, target)
        self._close_clip_popover()

    def _flash_clip_label(self, label: Gtk.Label, message: str) -> None:
        previous = label.get_label()
        label.set_label(message)

        def _restore() -> bool:
            try:
                if label.get_label() == message:
                    label.set_label(previous)
            except Exception:
                return False
            return False

        GLib.timeout_add(2000, _restore)

    def _on_copy_clip(self, _button: Gtk.Button, entry: dict[str, Any] | str) -> None:
        if isinstance(entry, str):
            if entry:
                self.get_clipboard().set(entry)
                self._toast("Copied")
            return
        if not isinstance(entry, dict):
            return
        if entry.get("kind") == "image":
            self._copy_clip_image(entry)
            return
        text = entry.get("text")
        if not isinstance(text, str) or not text:
            return
        self.get_clipboard().set(text)
        self._toast("Copied")

    def _copy_clip_image(self, entry: dict[str, Any]) -> None:
        ident = entry.get("id")
        if not isinstance(ident, str) or not hasattr(self.client, "get_clipboard_image"):
            self._toast("That image is not available")
            return
        try:
            mime, data = self.client.get_clipboard_image(ident)
        except BridgeError:
            self._toast("That image is not available")
            return
        if not isinstance(mime, str) or not mime.startswith("image/") or not data:
            self._toast("Could not copy the image")
            return
        try:
            provider = Gdk.ContentProvider.new_for_bytes(mime, GLib.Bytes.new(data))
            self.get_clipboard().set_content(provider)
        except Exception:
            self._toast("Could not copy the image")
            return
        self._toast("Copied")

    def _on_pin_clip(self, _button: Gtk.Button, entry: dict[str, Any]) -> None:
        ident = entry.get("id")
        if not isinstance(ident, str) or not hasattr(self.client, "pin_clipboard"):
            return
        try:
            self.client.pin_clipboard(ident, entry.get("pinned") is not True)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        self._reload_clip_now()

    def _on_edit_clip(self, button: object, entry: dict[str, Any]) -> None:
        if entry.get("masked") is True or entry.get("kind") == "image":
            return
        ident = entry.get("id")
        text = entry.get("text") if isinstance(entry.get("text"), str) else ""
        if not isinstance(ident, str):
            return
        self._show_clip_text(button, "Edit", text, editable=True, entry_id=ident)

    def _on_tag_clip(self, button: object, entry: dict[str, Any]) -> None:
        if entry.get("masked") is True:
            return
        ident = entry.get("id")
        if not isinstance(ident, str):
            return
        self._show_clip_tags(button, ident, _entry_tags(entry))

    def _on_search_clip(self, _button: Gtk.Button, entry: dict[str, Any]) -> None:
        if entry.get("masked") is True or entry.get("kind") == "image":
            return
        self._clip_search_ready = False
        try:
            fallback = load_ui_settings().clipboard_search_fallback
        except Exception:
            fallback = None
        outcome = open_clip_search(entry.get("text"), fallback)
        if outcome == "failed":
            self._toast("Could not open the browser")
        elif outcome != "opened":
            self._toast("No default search engine")

    def _preview_clipboard(self, row: Gtk.ListBoxRow) -> None:
        entry = getattr(row, "clip_entry", None)
        if isinstance(entry, dict) and entry.get("kind") == "image":
            self._show_clip_image(row, entry)
            return
        if getattr(row, "clip_masked", False) is True:
            return
        text = getattr(row, "clip_text", None)
        if not isinstance(text, str):
            return
        self._show_clip_text(row, "Preview", text, editable=False, entry_id=None)

    def _show_clip_image(self, parent: object, entry: dict[str, Any]) -> None:
        """Show the image file scaled to fit. SVG stays an image, not markup."""

        path = entry.get("path") if isinstance(entry.get("path"), str) else ""
        self._show_clip_popover(parent, _build_clip_image_preview(path))

    def _show_clip_text(
        self,
        parent: object,
        title: str,
        text: str,
        *,
        editable: bool,
        entry_id: str | None,
    ) -> None:
        on_save = None
        if editable and entry_id is not None:

            def on_save(body: str, ident: str = entry_id) -> None:
                self._save_clip_text(ident, body)

        self._show_clip_popover(
            parent,
            _build_text_editor(title, text, editable=editable, on_save=on_save),
        )

    def _save_clip_text(self, entry_id: str, text: str) -> None:
        if not hasattr(self.client, "edit_clipboard"):
            return
        try:
            saved = self.client.edit_clipboard(entry_id, text)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        if not saved:
            self._toast("That line could not be edited")
            return
        self._popover_reload = True
        self._close_clip_popover()

    def _show_clip_tags(
        self,
        parent: object,
        entry_id: str,
        tags: list[dict[str, str]],
    ) -> None:
        self._show_clip_popover(
            parent,
            _build_tag_editor(tags, lambda working: self._save_clip_tags(entry_id, working)),
        )

    def _save_clip_tags(self, entry_id: str, tags: list[dict[str, str]]) -> None:
        if not hasattr(self.client, "set_clipboard_tags"):
            return
        try:
            saved = self.client.set_clipboard_tags(entry_id, tags)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        if not saved:
            self._toast("Tags could not be saved")
            return
        self._popover_reload = True
        self._close_clip_popover()

    def _reload_clip_now(self) -> None:
        self._clip_gen += 1
        if hasattr(self.client, "get_clipboard"):
            try:
                self._clip_entries = self.client.get_clipboard()
            except BridgeError as exc:
                self._toast(friendly_bridge_message(exc))
                return
        self._fill_clipboard_rows()
        self._apply_clip_pending(loaded=True)

    def _apply_clip_pending(self, *, loaded: bool) -> None:
        pending = self._clip_pending
        if pending is None or not loaded:
            return
        self._clip_pending = None
        kind, ident = pending
        self.open_clip_editor(kind, ident)

    def _search_template(self) -> str | None:
        if self._clip_search_ready:
            return self._clip_search_template
        self._clip_search_ready = True
        try:
            desktop, setting = desktop_search_inputs()
            fallback = load_ui_settings().clipboard_search_fallback
            chosen, kind = choose_search_template(Path.home(), desktop, setting, fallback)
        except Exception:
            chosen, kind = None, "none"
        self._clip_search_template = chosen
        self._clip_search_kind = kind
        return self._clip_search_template

    def _on_delete_clip(self, _button: Gtk.Button, entry_id: str) -> None:
        if not hasattr(self.client, "delete_clipboard"):
            return
        try:
            self.client.delete_clipboard(entry_id)
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        self._clip_entries = [
            entry for entry in self._clip_entries if entry.get("id") != entry_id
        ]
        self._fill_clipboard_rows()

    def _confirm_clear_clipboard(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Clear clipboard history?",
            body=(
                "Unpinned copies saved on this machine are removed. "
                "Pinned items stay. The feed is not changed."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_clear_clipboard)
        self._clip_dialog = dialog
        dialog.present(self)

    def _on_clear_clipboard(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "clear" or not hasattr(self.client, "clear_clipboard"):
            return
        try:
            self.client.clear_clipboard()
        except BridgeError as exc:
            self._toast(friendly_bridge_message(exc))
            return
        self._clip_entries = [
            entry for entry in self._clip_entries if entry.get("pinned") is True
        ]
        self._fill_clipboard_rows()
        self._toast("Clipboard cleared")

    def _make_bot_row(self, bot: dict[str, Any], label: str, now: int) -> Gtk.ListBoxRow:
        state = bot.get("state")
        if not isinstance(state, str) or state not in _DOT_STATES:
            state = "unknown"
        dot = Gtk.Label(label="●")
        dot.add_css_class("tether-dot")
        dot.add_css_class(f"tether-dot-{state}")
        dot.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=label, xalign=0, hexpand=True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        head.append(dot)
        head.append(title)
        detail = Gtk.Label(label=bot_detail_line(bot, now), xalign=0)
        detail.add_css_class("dim-label")
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.append(head)
        box.append(detail)
        row = Gtk.ListBoxRow(child=box)
        row.bot_id = str(bot.get("name") or "")
        row.bot_label = label
        return row

    def _build_pages(self) -> Gtk.Box:
        box = Gtk.Box(spacing=6)
        self._page_todos = Gtk.ToggleButton(label="Todos")
        self._page_bots = Gtk.ToggleButton(label="Bots")
        self._page_clip = Gtk.ToggleButton(label="Clipboard")
        self._page_bots.set_group(self._page_todos)
        self._page_clip.set_group(self._page_todos)
        self._page_todos.set_active(True)
        self._page_todos.connect("toggled", self._on_page, "todos")
        self._page_bots.connect("toggled", self._on_page, "bots")
        self._page_clip.connect("toggled", self._on_page, "clipboard")
        box.append(self._page_todos)
        box.append(self._page_bots)
        box.append(self._page_clip)
        return box

    def _sync_pages(self) -> None:
        self._filling = True
        self._page_todos.set_active(self._page == "todos")
        self._page_bots.set_active(self._page == "bots")
        self._page_clip.set_active(self._page == "clipboard")
        self._filling = False

    def _sync_theme(self, manager: Adw.StyleManager, _pspec: Any = None) -> None:
        if manager.get_dark():
            self.add_css_class("tether-dark")
        else:
            self.remove_css_class("tether-dark")

    def _on_collapsed(self, split: Adw.NavigationSplitView, _pspec: Any) -> None:
        collapsed = bool(split.get_collapsed())
        self.back.set_visible(collapsed)
        self.detail_header.set_visible(collapsed)

    def _on_text_click(self, _gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        href = _href_at(self.text, self._link_tags, x, y)
        if not href:
            return
        try:
            self.open_uri(href)
        except GLib.Error as exc:
            self._toast(exc.message or "Could not open the link")

    def _on_text_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        href = _href_at(self.text, self._link_tags, x, y)
        if href:
            self.text.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        else:
            self.text.set_cursor(None)

    def _on_key(
        self,
        _controller: Any,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if control and keyval in {Gdk.KEY_f, Gdk.KEY_F}:
            self.search.grab_focus()
            return True
        if control and keyval in {Gdk.KEY_Return, Gdk.KEY_KP_Enter}:
            self._done_current()
            return True
        if control and keyval in {Gdk.KEY_w, Gdk.KEY_W}:
            self.close()
            return True
        if keyval == Gdk.KEY_Escape:
            if self._clip_popover is not None:
                self._close_clip_popover()
                return True
            self.close()
            return True
        if _focus_is_text(self) or _tag_entry_focused(self.get_focus()):
            return False
        if keyval == Gdk.KEY_Up:
            self._move(-1)
            return True
        if keyval == Gdk.KEY_Down:
            self._move(1)
            return True
        if keyval in {Gdk.KEY_Return, Gdk.KEY_KP_Enter}:
            row = self.list.get_selected_row()
            if row is not None:
                self.list.emit("row-activated", row)
            return True
        return False

    def _move(self, delta: int) -> None:
        current = self.list.get_selected_row()
        index = current.get_index() if current is not None else -1
        target = self.list.get_row_at_index(index + delta)
        if target is not None:
            self.list.select_row(target)

    def _build_views(self) -> Gtk.Box:
        box = Gtk.Box(spacing=6)
        first: Gtk.ToggleButton | None = None
        for name in VIEWS:
            button = Gtk.ToggleButton(label=_VIEW_LABELS[name])
            button.view_name = name
            if first is None:
                first = button
                button.set_active(True)
            else:
                button.set_group(first)
            button.connect("toggled", self._on_view)
            box.append(button)
        return box

    def _sync_views(self) -> None:
        child = self._view_buttons.get_first_child()
        while child is not None:
            name = getattr(child, "view_name", "")
            if isinstance(child, Gtk.ToggleButton) and name == self._view:
                child.set_active(True)
            child = child.get_next_sibling()


class ClipEditorWindow(Gtk.Window):
    """One clipboard editor, with no main window behind it."""

    def __init__(self, app: Adw.Application, title: str) -> None:
        super().__init__(application=app, title=title)
        self.set_title(title)
        self.set_icon_name(APP_ID)
        self._saved = False
        self._seen_active = False
        self._closing = False
        self._active_since = 0
        self._close_later = 0
        self._tag_entry: Gtk.Entry | None = None
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._status = Gtk.Label(xalign=0)
        self._status.set_wrap(True)
        self._status.set_visible(False)
        _pad_box(self._status)
        outer.append(self._slot)
        outer.append(self._status)
        self.set_child(outer)
        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close_request)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_editor_key)
        self.add_controller(controller)

    def set_editor(self, child: Gtk.Widget) -> None:
        while (old := self._slot.get_first_child()) is not None:
            self._slot.remove(old)
        self._slot.append(child)

    def note(self, text: str) -> None:
        self._status.set_label(text)
        self._status.set_visible(bool(text))

    def show_message(self, text: str) -> None:
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_halign(Gtk.Align.START)
        _pad_box(label)
        self.set_editor(label)

    def finish_saved(self) -> None:
        self._saved = True
        self.dismiss()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._clear_close_later()
        self.close()

    def _clear_close_later(self) -> None:
        if self._close_later:
            GLib.source_remove(self._close_later)
            self._close_later = 0

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        self._closing = True
        self._clear_close_later()
        return False

    def _on_active_changed(self, *_args: object) -> None:
        if self.is_active():
            self._seen_active = True
            if not self._active_since:
                self._active_since = GLib.get_monotonic_time()
                _focus_tag_entry(self._tag_entry)
            return
        if not self._seen_active or self._saved or self._closing:
            return
        GLib.idle_add(self._close_if_inactive)

    def _close_if_inactive(self) -> bool:
        self._close_later = 0
        if self._saved or self._closing or self.is_active() or not self._seen_active:
            return False
        if _mapped_popover(self) is not None:
            self._schedule_inactive_close()
            return False
        # A dropdown, or the window taking focus, can look inactive for a moment.
        since = self._active_since
        if since and GLib.get_monotonic_time() - since < 300_000:
            self._schedule_inactive_close()
            return False
        self.dismiss()
        return False

    def _schedule_inactive_close(self) -> None:
        if self._close_later:
            return
        self._close_later = GLib.timeout_add(300, self._close_if_inactive)

    def _on_editor_key(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval != Gdk.KEY_Escape or self._saved:
            return False
        open_popover = _mapped_popover(self)
        if open_popover is not None:
            open_popover.popdown()
            return True
        self.dismiss()
        return True


class WindowApp(Adw.Application):
    """Single instance. ``select-item`` opens or raises the window."""

    def __init__(self, client: Any | None = None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._client = client
        self.window: TodoWindow | None = None
        self._linger = 0
        self._clip_editor: ClipEditorWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        _install_css()
        action = Gio.SimpleAction.new("select-item", GLib.VariantType.new("s"))
        action.connect("activate", self._on_select_item)
        self.add_action(action)

    def do_activate(self) -> None:
        if self.window is None:
            client = self._client if self._client is not None else BridgeClient()
            self.window = TodoWindow(self, client)
            self.window.connect("close-request", self._on_close)
        self.window.present()
        self.window.refresh()
        self._release_linger()

    def _on_close(self, window: TodoWindow) -> bool:
        """Keep the process up briefly so the next open is not a cold start."""

        window._flush_due(True)
        window._undo_holds.clear()
        window.drop_undo_timers()
        self.hold()
        self.window = None
        if self._linger:
            GLib.source_remove(self._linger)
        self._linger = GLib.timeout_add(LINGER_MS, self._end_linger)
        return False

    def _end_linger(self) -> bool:
        self._linger = 0
        self.release()
        return GLib.SOURCE_REMOVE

    def _release_linger(self) -> None:
        if not self._linger:
            return
        GLib.source_remove(self._linger)
        self._linger = 0
        self.release()

    def _on_select_item(self, _action: Gio.SimpleAction, parameter: GLib.Variant | None) -> None:
        key = parameter.get_string() if parameter is not None else ""
        clip = _clip_window_action(key)
        if clip is not None:
            self.open_clip_editor(*clip)
            return
        if self.window is None:
            self.activate()
        if self.window is not None:
            self.window.select_key(key)

    def open_clip_editor(self, kind: str, ident: str) -> None:
        title = _EDITOR_TITLES.get(kind)
        if title is None or not isinstance(ident, str):
            return
        client = self._editor_client()
        width, height = _EDITOR_SIZE.get(kind, (360, 320))
        editor = ClipEditorWindow(self, title)
        editor.set_default_size(width, height)
        previous = getattr(self, "_clip_editor", None)
        self._clip_editor = editor
        if previous is not None and not previous._closing:
            previous.dismiss()
        editor.present()

        def apply(entries: list[dict[str, Any]], error: BridgeError | None) -> None:
            if editor._closing or editor._saved:
                return
            if error is not None:
                editor.show_message(friendly_bridge_message(error))
                return
            entry = _find_clip(entries, ident)
            if entry is None:
                editor.show_message("That copy is gone")
                return
            self._fill_clip_editor(editor, kind, entry, client)

        _load_clip_entries(client, apply)

    def _editor_client(self) -> Any:
        if self.window is not None:
            return self.window.client
        if self._client is None:
            self._client = BridgeClient()
        return self._client

    def _editor_effort(self) -> str:
        window = self.window
        if window is not None:
            return window._context_effort()
        try:
            effort = load_ui_settings().context_effort
        except Exception:
            return "low"
        if effort in _EFFORT_TITLES:
            return effort
        return "low"

    def _editor_bots(self, client: Any) -> list[str]:
        window = self.window
        if window is not None:
            return window._context_bots()
        names = ["primary"]
        seen = {"primary"}
        fresh: object = []
        if hasattr(client, "bots"):
            try:
                fresh = client.bots()
            except Exception:
                fresh = []
        if isinstance(fresh, list):
            for bot in fresh:
                if not isinstance(bot, dict):
                    continue
                name = bot.get("name")
                if isinstance(name, str) and name and name not in seen:
                    seen.add(name)
                    names.append(name)
        rest = sorted(name for name in names if name != "primary")
        return ["primary", *rest]

    def _reload_editor_clipboard(self) -> None:
        window = self.window
        if window is None or window._page != "clipboard":
            return
        window._reload_clip_now()

    def _fill_clip_editor(
        self,
        editor: ClipEditorWindow,
        kind: str,
        entry: dict[str, Any],
        client: Any,
    ) -> None:
        blocked = _clip_editor_block(kind, entry)
        if blocked is not None:
            editor.show_message(blocked)
            return
        ident = entry.get("id")
        if not isinstance(ident, str):
            editor.show_message("That copy is gone")
            return
        if kind == "clip-edit":
            text = entry.get("text") if isinstance(entry.get("text"), str) else ""
            editor.set_editor(
                _build_text_editor(
                    "Edit",
                    text,
                    editable=True,
                    on_save=lambda body: self._save_editor_text(editor, client, ident, body),
                )
            )
            return
        if kind == "clip-tag":
            tag_box = _build_tag_editor(
                _entry_tags(entry),
                lambda tags: self._save_editor_tags(editor, client, ident, tags),
            )
            editor._tag_entry = tag_box.tag_entry
            editor.set_editor(tag_box)
            _focus_tag_entry(tag_box.tag_entry)
            return
        if kind == "clip-context":
            editor.set_editor(
                _build_context_editor(
                    self._editor_effort(),
                    self._editor_bots(client),
                    lambda target: self._send_editor_context(editor, client, ident, target),
                    editor.dismiss,
                )
            )

    def _save_editor_text(
        self,
        editor: ClipEditorWindow,
        client: Any,
        entry_id: str,
        text: str,
    ) -> None:
        if editor._closing or not hasattr(client, "edit_clipboard"):
            editor.note("That line could not be edited")
            return
        try:
            saved = client.edit_clipboard(entry_id, text)
        except BridgeError as exc:
            editor.note(friendly_bridge_message(exc))
            return
        if not saved:
            editor.note("That line could not be edited")
            return
        editor.finish_saved()
        self._reload_editor_clipboard()

    def _save_editor_tags(
        self,
        editor: ClipEditorWindow,
        client: Any,
        entry_id: str,
        tags: list[dict[str, str]],
    ) -> None:
        if editor._closing or not hasattr(client, "set_clipboard_tags"):
            editor.note("Tags could not be saved")
            return
        try:
            saved = client.set_clipboard_tags(entry_id, tags)
        except BridgeError as exc:
            editor.note(friendly_bridge_message(exc))
            return
        if not saved:
            editor.note("Tags could not be saved")
            return
        editor.finish_saved()
        self._reload_editor_clipboard()

    def _send_editor_context(
        self,
        editor: ClipEditorWindow,
        client: Any,
        entry_id: str,
        target: str,
    ) -> None:
        if editor._closing or not hasattr(client, "send_clipboard"):
            editor.note("Not sent: Bridge not running")
            return
        bot = target if isinstance(target, str) and target else "primary"
        try:
            result = client.send_clipboard(entry_id, "clip-todo-context", bot)
        except BridgeError as exc:
            editor.note(clip_send_message(exc))
            return
        if result != "sent":
            editor.note("Not sent")
            return
        editor.note("Sent")
        editor.finish_saved()


def apply_runs(
    buffer: Gtk.TextBuffer,
    runs: tuple[Run, ...],
    links: dict[str, Gtk.TextTag],
) -> None:
    """Insert runs and apply the named style tags. Links stay inert until a click."""

    buffer.set_text("")
    for run in runs:
        if not run.text:
            continue
        start_offset = buffer.get_char_count()
        buffer.insert(buffer.get_end_iter(), run.text)
        start = buffer.get_iter_at_offset(start_offset)
        end = buffer.get_end_iter()
        for name in run.tags:
            if name == "link":
                href = safe_http_url(run.href or "")
                if href:
                    buffer.apply_tag(_link_tag(buffer, href, links), start, end)
                continue
            style = buffer.get_tag_table().lookup(name)
            if style is not None:
                buffer.apply_tag(style, start, end)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else [sys.argv[0], *argv]
    try:
        app = WindowApp()
    except Exception:
        print(
            "tetherbot-window: GTK 4 and libadwaita are required.",
            file=sys.stderr,
        )
        return 1
    return app.run(args)


def _variant_names(value: Any) -> list[str]:
    """Keys or strings from a PropertiesChanged variant."""

    if value is None:
        return []
    if isinstance(value, dict):
        return [key for key in value if isinstance(key, str)]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    unpack = getattr(value, "unpack", None)
    if not callable(unpack):
        return []
    try:
        data = unpack()
    except Exception:
        return []
    return _variant_names(data)


def _open_uri(href: str) -> None:
    """Open a link in the default browser. Called only after a click."""

    Gio.AppInfo.launch_default_for_uri(href, None)


def _install_css() -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _install_icons(display)


def extension_icon_root() -> Path | None:
    """Icon theme root shipped with the extension, or the installed copy."""

    bundled = Path(__file__).resolve().parents[2] / "extension" / "icons"
    if (bundled / "hicolor").is_dir():
        return bundled
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    installed = base / "gnome-shell" / "extensions" / EXTENSION_UUID / "icons"
    if (installed / "hicolor").is_dir():
        return installed
    return None


def _install_icons(display: Gdk.Display) -> None:
    root = extension_icon_root()
    if root is None:
        return
    theme = Gtk.IconTheme.get_for_display(display)
    path = str(root)
    if path not in set(theme.get_search_path()):
        theme.add_search_path(path)


def _install_style_tags(buffer: Gtk.TextBuffer) -> None:
    table = buffer.get_tag_table()

    def add(name: str, **props: Any) -> None:
        tag = Gtk.TextTag.new(name)
        for key, value in props.items():
            tag.set_property(key, value)
        table.add(tag)

    add("bold", weight=Pango.Weight.BOLD)
    add("italic", style=Pango.Style.ITALIC)
    add("code", family="monospace", background="#00000018")
    add("codeblock", family="monospace", background="#00000018", left_margin=8)
    add("h1", weight=Pango.Weight.BOLD, scale=1.6)
    add("h2", weight=Pango.Weight.BOLD, scale=1.35)
    add("h3", weight=Pango.Weight.BOLD, scale=1.15)
    add("quote", style=Pango.Style.ITALIC, left_margin=12)
    add("bullet")
    add("number")
    add("task")
    add("task-done")


def _link_tag(buffer: Gtk.TextBuffer, href: str, links: dict[str, Gtk.TextTag]) -> Gtk.TextTag:
    cached = links.get(href)
    if cached is not None:
        return cached
    table = buffer.get_tag_table()
    existing = table.lookup(href)
    if existing is not None:
        links[href] = existing
        return existing
    dark = Adw.StyleManager.get_default().get_dark()
    tag = Gtk.TextTag.new(href)
    tag.set_property("underline", Pango.Underline.SINGLE)
    tag.set_property("foreground", "#99c1f1" if dark else "#1c71d8")
    table.add(tag)
    links[href] = tag
    return tag


def _href_at(view: Gtk.TextView, links: dict[str, Gtk.TextTag], x: float, y: float) -> str:
    found = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
    if isinstance(found, tuple) and len(found) == 3:
        ok, buf_x, buf_y = found
        if not ok:
            return ""
    elif isinstance(found, tuple) and len(found) == 2:
        buf_x, buf_y = found
    else:
        return ""
    _inside, iterator = view.get_iter_at_location(buf_x, buf_y)
    for tag in iterator.get_tags():
        name = tag.get_property("name")
        href = safe_http_url(name if isinstance(name, str) else "")
        if href and href in links:
            return href
    return ""


def _now_ms() -> int:
    return int(time.time() * 1000)


class CenterUndoBar(Gtk.Widget):
    """Undo fill that shrinks toward the middle, from both ends.

    The label is the size request, so the button stays one line tall.
    """

    def __init__(self) -> None:
        super().__init__()
        self._fraction = 1.0
        self._label: Gtk.Label | None = Gtk.Label(label="Undo")
        self._label.set_parent(self)
        self.set_layout_manager(Gtk.BinLayout())
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.add_css_class("tether-undo-bar")

    def set_fraction(self, fraction: float) -> None:
        value = float(fraction)
        if value < 0:
            value = 0.0
        elif value > 1:
            value = 1.0
        if value == self._fraction:
            return
        self._fraction = value
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = self.get_width()
        height = self.get_height()
        x, bar = center_bar_span(width, self._fraction)
        if bar > 0 and height > 0:
            rect = Graphene.Rect()
            rect.init(x, 0, bar, height)
            color = Gdk.RGBA()
            color.red = 28 / 255
            color.green = 113 / 255
            color.blue = 216 / 255
            color.alpha = 0.35
            rounded = Gsk.RoundedRect()
            rounded.init_from_rect(rect, min(6, height / 2, bar / 2))
            snapshot.push_rounded_clip(rounded)
            snapshot.append_color(color, rect)
            snapshot.pop()
        if self._label is not None:
            self.snapshot_child(self._label, snapshot)

    def do_dispose(self) -> None:
        label = self._label
        self._label = None
        if label is not None and label.get_parent() is self:
            label.unparent()
        Gtk.Widget.do_dispose(self)


def _label_button(label: str) -> Gtk.Button:
    """A detail button that stays the size of its label."""

    button = Gtk.Button(label=label)
    button.set_hexpand(False)
    button.set_vexpand(False)
    button.set_halign(Gtk.Align.START)
    button.set_valign(Gtk.Align.CENTER)
    return button


def _undo_button(*, detail: bool = False) -> tuple[Gtk.Button, CenterUndoBar]:
    """An Undo button whose bar shrinks toward the middle."""

    bar = CenterUndoBar()
    bar.set_fraction(1)
    button = Gtk.Button(child=bar)
    button.add_css_class("tether-undo")
    if detail:
        button.add_css_class("tether-detail-undo")
    button.set_hexpand(False)
    button.set_vexpand(False)
    button.set_halign(Gtk.Align.START)
    button.set_valign(Gtk.Align.CENTER)
    return button, bar


class SlotPage(Gtk.Widget):
    """Holds one button that fills a fixed slot."""

    def __init__(self, child: Gtk.Widget) -> None:
        super().__init__()
        self._child: Gtk.Widget | None = child
        child.set_parent(self)
        self.set_hexpand(False)
        self.set_vexpand(False)

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        child = self._child
        if child is None:
            return (0, 0, -1, -1)
        measured = child.measure(orientation, for_size)
        return (
            measured.minimum,
            measured.natural,
            measured.minimum_baseline,
            measured.natural_baseline,
        )

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        del baseline
        child = self._child
        if child is None:
            return
        child.allocate(width, height, -1, None)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if self._child is not None:
            self.snapshot_child(self._child, snapshot)

    def do_dispose(self) -> None:
        child = self._child
        self._child = None
        if child is not None and child.get_parent() is self:
            child.unparent()
        Gtk.Widget.do_dispose(self)


def _button_slot(action: Gtk.Button, undo: Gtk.Button) -> Gtk.Stack:
    """One fixed slot. Undo replaces the action button without moving the row.

    The slot is as wide as the wider of the two buttons. The visible button
    fills that slot, so the gap before the next button is only the row
    spacing. Neighbors do not shift, and the six buttons are not stretched
    to one shared width.
    """

    action_page = SlotPage(action)
    undo_page = SlotPage(undo)
    stack = Gtk.Stack()
    stack.set_hhomogeneous(True)
    stack.set_vhomogeneous(False)
    stack.set_hexpand(False)
    stack.set_vexpand(False)
    stack.set_halign(Gtk.Align.START)
    stack.set_valign(Gtk.Align.CENTER)
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    stack.add_child(action_page)
    stack.add_child(undo_page)
    stack.set_visible_child(action_page)
    stack.action_page = action_page
    stack.undo_page = undo_page
    return stack


class ActionRow(Gtk.Widget):
    """Detail buttons at label size. Extra buttons wrap instead of clipping."""

    def __init__(self, children: tuple[Gtk.Widget, ...]) -> None:
        super().__init__()
        self._children = list(children)
        self._spacing = 8
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        for child in self._children:
            child.set_parent(self)

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        if orientation == Gtk.Orientation.HORIZONTAL:
            widest = 0
            total = 0
            for index, child in enumerate(self._children):
                measured = child.measure(Gtk.Orientation.HORIZONTAL, -1)
                widest = max(widest, measured.minimum)
                total += measured.natural
                if index:
                    total += self._spacing
            return (widest, max(widest, total), -1, -1)
        height = self._place(for_size if for_size > 0 else 100_000, allocate=False)
        return (height, height, -1, -1)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        del height, baseline
        self._place(width, allocate=True)

    def _place(self, width: int, *, allocate: bool) -> int:
        x = 0
        y = 0
        row_height = 0
        limit = width if width > 0 else 100_000
        for child in self._children:
            child_width = child.measure(Gtk.Orientation.HORIZONTAL, -1).natural
            child_height = child.measure(Gtk.Orientation.VERTICAL, -1).natural
            if x > 0 and x + child_width > limit:
                x = 0
                y += row_height + self._spacing
                row_height = 0
            if allocate:
                point = Graphene.Point()
                point.init(x, y)
                child.allocate(
                    child_width,
                    child_height,
                    -1,
                    Gsk.Transform().translate(point),
                )
            x += child_width + self._spacing
            row_height = max(row_height, child_height)
        return y + row_height

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        for child in self._children:
            self.snapshot_child(child, snapshot)

    def do_dispose(self) -> None:
        children = self._children
        self._children = []
        for child in children:
            if child.get_parent() is self:
                child.unparent()
        Gtk.Widget.do_dispose(self)


def _action_row(*children: Gtk.Widget) -> ActionRow:
    """The detail buttons. They wrap instead of clipping, and they do not grow."""

    return ActionRow(children)


def _copy_icon(label: str) -> Gtk.Button:
    button = Gtk.Button(icon_name="edit-copy-symbolic")
    button.add_css_class("flat")
    button.set_valign(Gtk.Align.START)
    button.set_tooltip_text(label)
    button.update_property([Gtk.AccessibleProperty.LABEL], [label])
    return button


_CLIP_TONES = frozenset(
    {"red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"}
)


def _image_query_hit(entry: dict[str, Any], query: str) -> bool:
    """True when the label or the type matches. The bytes are not searched."""

    mime = entry.get("mime") if isinstance(entry.get("mime"), str) else ""
    size = entry.get("size") if isinstance(entry.get("size"), int) else 0
    label = image_label(mime, size).casefold()
    return query in label or query in mime.casefold()


def _clip_picture(entry: dict[str, Any]) -> Gtk.Picture | None:
    """A 48px thumbnail from the thumb file, or the image file when it exists."""

    thumb = entry.get("thumb") if isinstance(entry.get("thumb"), str) else ""
    path = entry.get("path") if isinstance(entry.get("path"), str) else ""
    shown = thumb or path
    if not shown:
        return None
    picture = Gtk.Picture()
    picture.add_css_class("tether-clip-thumb")
    picture.set_size_request(48, 48)
    picture.set_valign(Gtk.Align.CENTER)
    picture.set_can_shrink(True)
    if hasattr(Gtk, "ContentFit"):
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
    if Path(shown).is_file():
        try:
            picture.set_paintable(Gdk.Texture.new_from_filename(shown))
        except Exception:
            return picture
    return picture


def _as_bytes(value: object) -> bytes | None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, list) and all(_byte(item) for item in value):
        return bytes(value)
    return None


def _byte(item: object) -> bool:
    return isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255


def _clip_icon(icon_name: str, tooltip: str, sensitive: bool = True) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon_name)
    button.add_css_class("flat")
    button.add_css_class("tether-clip-action")
    button.set_tooltip_text(tooltip)
    button.set_sensitive(sensitive)
    button.set_valign(Gtk.Align.CENTER)
    button.set_size_request(28, 28)
    button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    return button


def _clip_dot(name: str, color: str) -> Gtk.Label:
    tone = color if color in _CLIP_TONES else "gray"
    dot = Gtk.Label(label="●")
    dot.add_css_class("tether-clip-dot")
    dot.add_css_class(f"tone-{tone}")
    dot.set_tooltip_text(name)
    dot.set_valign(Gtk.Align.CENTER)
    return dot


def _clip_actions(buttons: list[Gtk.Button]) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    box.set_valign(Gtk.Align.CENTER)
    for index, button in enumerate(buttons):
        if index:
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.add_css_class("tether-clip-sep")
            box.append(sep)
        box.append(button)
    return box


def _clip_tag_names(entry: dict[str, Any]) -> list[str]:
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return []
    names: list[str] = []
    for tag in tags:
        if isinstance(tag, dict) and isinstance(tag.get("name"), str):
            names.append(tag["name"])
    return names


def _chip(label: str, tone: str) -> Gtk.Label:
    widget = Gtk.Label(label=label)
    widget.add_css_class("tether-chip")
    widget.add_css_class(f"tone-{tone}")
    return widget


def _fill_chip_box(box: Gtk.FlowBox, chips: Any) -> None:
    _clear_box(box)
    if not isinstance(chips, dict):
        return
    ordered: list[dict[str, Any]] = []
    for name in ("priority", "due", "created", "waiting"):
        chip = chips.get(name)
        if isinstance(chip, dict) and chip.get("label"):
            ordered.append(chip)
    for chip in chips.get("tags") or []:
        if isinstance(chip, dict) and chip.get("label"):
            ordered.append(chip)
    for chip in ordered:
        box.append(_chip(str(chip["label"]), str(chip.get("tone") or "neutral")))


def _display_elapsed(timer: dict[str, Any]) -> float:
    """Prefer the bridge elapsed value. Fall back to the stored segments."""

    elapsed = timer.get("elapsed_s")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
        return float(elapsed)
    accumulated = timer.get("accumulated_s")
    if isinstance(accumulated, (int, float)) and not isinstance(accumulated, bool):
        base = float(accumulated)
    else:
        base = 0.0
    if timer.get("state") != "running":
        return base
    since = timer.get("running_since")
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        return base
    return base + max(0.0, time.time() - float(since))


def _clear_box(box: Gtk.Widget) -> None:
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def _natural_height(widget: Gtk.Widget, width: int = -1) -> int:
    try:
        measured = widget.measure(Gtk.Orientation.VERTICAL, width)
    except Exception:
        return 0
    if not measured or len(measured) < 2:
        return 0
    natural = measured[1]
    if isinstance(natural, int) and natural > 0:
        return natural
    return 0


def _widget_inside(widget: Gtk.Widget | None, ancestor: Gtk.Widget) -> bool:
    while widget is not None:
        if widget == ancestor:
            return True
        widget = widget.get_parent()
    return False


def _collect_flags(widget: Gtk.Widget) -> Gtk.StateFlags:
    flags = widget.get_state_flags()
    child = widget.get_first_child()
    while child is not None:
        flags |= _collect_flags(child)
        child = child.get_next_sibling()
    return flags


def _pointer_on_row(row: Gtk.ListBoxRow) -> bool:
    """True when the pointer or a press is still on this row."""

    hot = Gtk.StateFlags.PRELIGHT | Gtk.StateFlags.ACTIVE
    return bool(_collect_flags(row) & hot)


def _row_blocked(window: TodoWindow, row: Gtk.ListBoxRow) -> bool:
    """True when unparenting this row can crash a pointer or key grab."""

    if _pointer_on_row(row):
        return True
    focus = window.get_focus()
    return focus is not None and focus is not window.list and _widget_inside(focus, row)


def _dispose_widget(widget: Gtk.Widget) -> None:
    """Drop the Python wrapper's hold on a widget that has left the list."""

    dispose = getattr(widget, "run_dispose", None)
    if not callable(dispose):
        return
    try:
        dispose()
    except Exception:
        return


def _focus_is_text(window: TodoWindow) -> bool:
    """True when Enter belongs to a text widget, including the start field.

    GTK 4 puts focus on the entry's inner text, not on the entry itself.
    """

    focus = window.get_focus()
    if focus is None:
        return False
    if focus is window.text or focus is window.note_view or focus is window.start_entry:
        return True
    return _widget_inside(focus, window.start_entry) or _widget_inside(focus, window.note_view)


def _object_dict(raw: tuple[Any, ...]) -> dict[str, Any]:
    if not raw or not isinstance(raw[0], str):
        return {}
    parsed = json.loads(raw[0])
    return parsed if isinstance(parsed, dict) else {}


def _object_list(raw: tuple[Any, ...]) -> list[dict[str, Any]]:
    if not raw or not isinstance(raw[0], str):
        return []
    parsed = json.loads(raw[0])
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


if __name__ == "__main__":
    raise SystemExit(main())

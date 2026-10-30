# SPDX-License-Identifier: GPL-2.0-or-later
"""The window process stays off the network. GTK is not imported here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOW_FILES = (
    ROOT / "bridge" / "tetherbot" / "window.py",
    ROOT / "bridge" / "tetherbot" / "markdown.py",
    ROOT / "bridge" / "tetherbot" / "window_query.py",
    ROOT / "bridge" / "tetherbot" / "window_launch.py",
)
FORBIDDEN = (
    "urllib",
    "Soup",
    "subprocess",
    "WebKit",
    "webkit",
    "fetch(",
    "XMLHttpRequest",
    "socket",
    "requests",
    "httpx",
    "Secret",
)


def test_window_sources_do_not_touch_the_network_or_secrets():
    for path in WINDOW_FILES:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{path.name} contains {token}"
    window = (ROOT / "bridge" / "tetherbot" / "window.py").read_text(encoding="utf-8")
    assert "launch_default_for_uri" in window
    assert "select-item" in window
    assert "PerformAction" in window
    assert "Undo" in window
    assert "SendToBot" in window
    launch = (ROOT / "bridge" / "tetherbot" / "window_launch.py").read_text(encoding="utf-8")
    assert "call_sync" not in launch
    assert "ActivateAction" in launch
    assert "new_sync" not in window
    assert "LINGER_MS = 60_000" in window
    assert "GetTimer" in window
    assert "Start timer" in window
    assert "Stop timer" in window
    assert "Copy Todo" in window
    assert "Copy title" in window
    assert "Copy body" in window
    assert "edit-copy-symbolic" in window
    assert "set_icon_name(APP_ID)" in window
    assert "set_titlebar" not in window
    assert "ToolbarView" in window
    assert "WindowControls" not in window
    assert "WINDOW_DEFAULT_WIDTH = 1520" in window
    assert "WINDOW_MIN_WIDTH = 1400" in window
    assert "set_default_size(WINDOW_DEFAULT_WIDTH, 800)" in window
    assert "set_size_request(WINDOW_MIN_WIDTH, 680)" in window
    assert "window_width < WINDOW_MIN_WIDTH" in window
    assert "window_width = WINDOW_DEFAULT_WIDTH" in window
    assert 'label="Note"' in window
    assert '_label_button("Done with note")' in window
    assert "CenterUndoBar" in window
    assert "center_bar_span" in window
    assert "_schedule_after_send" in window
    assert "hold[\"failed\"] = True" in window
    assert "KEY_w" in window
    assert "KEY_Escape" in window
    assert "AssignTimer" in window
    assert "DismissTimer" in window
    assert "GetItemTime" in window
    assert "SetTrackedTotal" in window
    assert "DeleteTimeRecord" in window
    assert "Delete this time record?" in window
    assert "AdjustTimerStart" in window
    assert "merge_undo_items" in window
    assert "tether-undo" in window
    assert 'label="Clipboard"' in window
    assert "GetClipboard" in window
    assert "GetClipboardImage" in window
    assert "Images are not edited" in window
    assert "Images are not searched" in window
    assert "new_for_bytes" in window
    assert "ContentFit.CONTAIN" in window
    assert "DeleteClipboard" in window
    assert "ClearClipboard" in window
    assert "Clear history" in window
    assert "Search clipboard" in window
    assert "Hidden password" in window
    assert "Search the web" in window
    assert '"Preview"' in window
    assert "document-edit-symbolic" in window
    assert "tetherbot-tag-symbolic" in window
    assert "set_max_width_chars(1)" in window
    assert "set_can_shrink(False)" in window
    assert "PolicyType.NEVER" in window
    assert "view-pin-symbolic" in window
    assert "edit-copy-symbolic" in window
    assert "system-search-symbolic" in window
    assert "edit-delete-symbolic" in window
    assert '"Edit"' in window
    assert '"Unpin" if pinned else "Pin"' in window
    assert "tether-pin-on" not in window
    fill = window.split("def _fill_clipboard_rows", 1)[1].split("\n    def _sync_clip_tags", 1)[0]
    assert '"Pinned"' in fill
    assert '"Unpinned"' in fill
    assert fill.index('"Pinned"') < fill.index('"Unpinned"')
    assert "_clip_separator_row" in fill
    assert "_clip_heading_row" in fill
    assert "tether-clip-sep" in window
    assert "EllipsizeMode.END" in window
    assert "set_max_children_per_line(6)" not in window
    assert "editable=False" in window
    assert "Hidden passwords are not searched" in window
    assert "Hidden passwords are not tagged" in window
    assert "tetherbot-check-symbolic" in window
    assert "tetherbot-square-check-symbolic" in window
    assert "tetherbot-circle-help-symbolic" in window
    assert "clip-todo" in window
    assert "clip-todo-context" in window
    assert "clip-ask" in window
    assert "SendClipboard" in window
    assert '"(sss)"' in window
    assert "tether-effort-low" in window
    assert "tether-effort-medium" in window
    assert "tether-effort-high" in window
    assert "_prompt_clip_context" in window
    assert '"Effort:"' in window
    assert '"Sent"' in window
    assert "_show_clip_popover" in window
    assert "set_autohide(True)" in window
    assert '"That clip is gone."' in window
    assert "tether-clip-target" in window
    assert "Sending… will retry" in window
    assert "Couldn't send Done. Try again." in window
    assert "class ClipEditorWindow" not in window
    assert "clip-context" in window
    tag_editor = window.split("def _build_tag_editor", 1)[1].split(
        "\ndef _build_context_editor", 1
    )[0]
    assert "EventControllerMotion" not in tag_editor
    assert '"New tag"' in tag_editor
    assert '"Applied tags"' in tag_editor
    assert '"None yet"' in tag_editor
    assert "add_tag(name_row)" in tag_editor
    assert "release_tag_editor" in tag_editor
    text_editor = window.split("def _build_text_editor", 1)[1].split(
        "\ndef _focus_tag_entry", 1
    )[0]
    assert '"Cancel"' in text_editor
    assert '"Save"' in text_editor
    assert "_queue_clip_popover_close" in window
    assert "_clip_rebuild_deferred" in window
    assert "_drop_closed_popover" in window
    assert "faulthandler.enable" in window
    assert "window-faults.log" in window
    assert "_close_saved" not in window
    assert window.count('notify::is-active') == 1
    active = window.split("def _on_window_active", 1)[1].split("\n    def ", 1)[0]
    assert "_commit_current_note_draft" in active
    assert "close(" not in active
    assert "_close_if_inactive" not in window
    shifts = window.split("self.edit_start_box = Gtk.Box", 1)[1].split(
        "self.start_entry", 1
    )[0]
    assert shifts.index('"-1m"') < shifts.index('"-5m"')
    for name in (
        "_show_clip_text",
        "_show_clip_tags",
        "_show_clip_image",
        "_prompt_clip_context",
    ):
        body = window.split(f"    def {name}(", 1)[1].split("\n    def ", 1)[0]
        assert "Gtk.Window(" not in body
        assert "_show_clip_popover" in body
    assert "Not sent" in window
    assert "clip_send_message" in window
    assert "Images are not sent" in window
    assert "Hidden passwords are not sent" in window
    assert "Uses the search fallback from Settings" in window
    assert "_clip_tag_guard" in window
    assert "chosen == self._clip_tag" in window
    search = (ROOT / "bridge" / "tetherbot" / "clipboard_search.py").read_text(encoding="utf-8")
    assert "google.com" not in window
    assert "duckduckgo.com" not in window
    assert search.count("https://www.google.com/") == 1
    assert "FALLBACK_SEARCH_TEMPLATE" in search


def test_priority_chip_sits_in_the_list_chip_row():
    window = (ROOT / "bridge" / "tetherbot" / "window.py").read_text(encoding="utf-8")
    make = window.split("    def _make_row(", 1)[1].split("    def _show_item(", 1)[0]
    top = make.split("top = Gtk.Box", 1)[1].split("chip_row = Gtk.Box", 1)[0]
    assert "priority" not in top
    assert "top.append(title)" in top
    chips = make.split("chip_row = Gtk.Box", 1)[1].split("box = Gtk.Box", 1)[0]
    bot = chips.index('item.get("display_name")')
    due = chips.index('chips.get("due")')
    priority = chips.index('chips.get("priority")')
    tags = chips.index('chips.get("tags")')
    tracked = chips.index("format_tracked")
    assert bot < due < priority < tags < tracked

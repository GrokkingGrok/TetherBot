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
    assert 'label="Done with note"' in window
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

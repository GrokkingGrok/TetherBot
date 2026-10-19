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

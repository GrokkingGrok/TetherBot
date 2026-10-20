# SPDX-License-Identifier: GPL-2.0-or-later
"""The extension ships the bus XML and does not grow a network path."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
DATA_XML = ROOT / "data" / "io.github.grokkinggrok.TetherBot1.xml"
SHIPPED_XML = EXTENSION / "io.github.grokkinggrok.TetherBot1.xml"

FORBIDDEN = (
    "gi://Soup",
    "SocketClient",
    "fetch(",
    "GLib.spawn",
    "spawn_command_line",
    "XMLHttpRequest",
)


def _code(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def test_shipped_xml_matches_the_bus_source():
    assert SHIPPED_XML.read_text(encoding="utf-8") == DATA_XML.read_text(encoding="utf-8")


def test_extension_code_has_no_network_api():
    for path in sorted(EXTENSION.glob("*.js")):
        code = _code(path.read_text(encoding="utf-8"))
        for token in FORBIDDEN:
            assert token not in code, f"{path.name} contains {token}"


# Constructors and helpers Shell 46–50 removed. Using one of these throws
# while the extension is loading or the first time that line runs.
REMOVED_CLUTTER = (
    "Clutter.Canvas",
    "Clutter.Image",
    "Clutter.ClickAction",
    "Clutter.TapAction",
    "Clutter.DragAction",
    "Clutter.Color",
    "Clutter.cairo_set_source_color",
    "Clutter.Container",
    "Clutter.CairoTexture",
    "Clutter.Texture",
    "get_seat_state",
)


def test_extension_does_not_use_removed_clutter_apis():
    for path in sorted(EXTENSION.glob("*.js")):
        code = _code(path.read_text(encoding="utf-8"))
        for token in REMOVED_CLUTTER:
            assert token not in code, f"{path.name} contains {token}"


def test_disable_drops_the_proxy_and_handlers():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "makeProxyWrapper" in text
    assert "DO_NOT_AUTO_START" in text
    assert "startServiceCall" in text
    view = (EXTENSION / "view.js").read_text(encoding="utf-8")
    assert "StartServiceByName" in view
    assert "io.github.grokkinggrok.TetherBot1.xml" in text
    disable = text.split("disable()", 1)[1].split("\n    _", 1)[0]
    assert "bus_unwatch_name" in disable
    assert "_dropProxy" in disable
    assert "_source.destroy" in disable
    assert "_indicator?.destroy" in disable
    assert "_proxy = null" in (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "disconnectSignal" in text
    assert "_tickSource" in disable
    assert "source_remove" in disable
    assert "GetTimerRemote" in text
    assert "keepAssigning" in text
    assert "todoActivation" in text
    menu = text.split("    _buildMenu() {", 1)[1].split("\n    _", 1)[0]
    added = [line.strip() for line in menu.splitlines() if "addMenuItem" in line]
    order = " ".join(added)
    timer_at = order.index("_timerSection")
    todo_at = order.index("_todoSection")
    ask_at = order.index("_askSection")
    bot_at = order.index("_botSection")
    open_at = order.index("_openItem")
    assert timer_at < todo_at < ask_at < bot_at < open_at
    assert "compactBotSection" in view
    render = text.split("    _render() {", 1)[1].split("\n    _", 1)[0]
    assert "keepAssigning" in render
    assert "_expireAssign" not in text
    assert "undo.kind === 'assign'" not in text
    assert "network-offline" not in text
    assert "mail-unread" not in text
    css = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
    assert "font-variant-numeric" in css
    assert "tetherbot-time" in css
    assert "min-width: 4.8em" not in css
    assert "topBarWidthSample" in text
    icon = text.split("this._icon = new St.Icon({", 1)[1].split("});", 1)[0]
    assert "icon_size" not in icon
    assert "system-status-icon" in icon
    assert "icon-size" not in css
    assert "tetherbot-undo" in css
    assert "max-width: 5.2em" in css
    assert "undoFraction" in text
    assert "Gio.FileIcon" in text
    assert "face-symbolic.svg" in text
    assert "St.DrawingArea" not in text
    assert "get_foreground_color" not in text
    assert "0.86" not in text
    mark = text.split("    _markDone(row) {", 1)[1].split("\n    _", 1)[0]
    assert "_perform(" not in mark
    assert "shareUndoWindow" in mark
    flush = text.split("    _flushDue(", 1)[1].split("\n    _", 1)[0]
    assert "_perform('done'" in flush
    close = text.split("open-state-changed", 1)[1].split("});", 1)[0]
    assert "_flushDue(true)" in close
    face = (EXTENSION / "icons" / "face-symbolic.svg").read_text(encoding="utf-8")
    assert face.count("<circle ") == 2
    assert 'r="1.55"' in face
    assert "Q8 12.15" in face
    assert "#" not in face
    assert "currentColor" in face
    assert "M8 4V1.6" not in face
    fill = text.split("    _fillTimer(block) {", 1)[1].split("\n    _", 1)[0]
    assert fill.index("chipLabel(block.bot") < fill.index("block.subject")
    window = (ROOT / "bridge" / "tetherbot" / "window.py").read_text(encoding="utf-8")
    assert "g-properties-changed" in window
    assert "properties_need_reload" in window
    icons = EXTENSION / "icons"
    variants = {
        "face-symbolic.svg": 2,
        "face-dot-symbolic.svg": 3,
        "face-ring-symbolic.svg": 2,
        "face-slash-symbolic.svg": 2,
        "face-triangle-symbolic.svg": 2,
    }
    for name, circles in variants.items():
        body = (icons / name).read_text(encoding="utf-8")
        assert name.endswith("-symbolic.svg")
        assert "#" not in body
        assert "currentColor" in body
        assert 'r="1.55"' in body
        assert body.count("<circle ") == circles
        assert "error" not in body
        assert "warning" not in body
    ring = (icons / "face-ring-symbolic.svg").read_text(encoding="utf-8")
    assert "A1.65" in ring
    dot = (icons / "face-dot-symbolic.svg").read_text(encoding="utf-8")
    assert 'r="2.4"' in dot

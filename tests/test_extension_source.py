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
    assert "_clipIndicator?.destroy" in disable
    assert "_unwatchClipboard" in disable
    assert "_proxy = null" in (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "disconnectSignal" in text
    assert "_tickSource" in disable
    assert "source_remove" in disable
    assert "_settings.disconnect" in disable
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
    assert "* 0.25" in view
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
    assert ".tetherbot-bot-warn" in css
    assert ".tetherbot-bot-alert" in css
    assert "tetherbot-bot-warn" in text
    assert ".tetherbot-badge-red" in css
    assert "#ed333b" in css
    assert ".tetherbot-badge-blue" in css
    assert "#3584e4" in css
    assert "tetherbot-mark-ring" not in css
    assert "border-color: #ed333b" not in css
    assert "max-width: 5.2em" in css
    assert "undoFraction" in text
    assert "Gio.FileIcon" in text
    assert "face-symbolic.svg" in text
    assert "tetherbot-badge-red" in text
    assert "tetherbot-badge-blue" in text
    assert "tetherbot-mark-ring" not in text
    assert "0.42" not in text
    assert "0.34" not in text
    assert "Clutter.FixedLayout" in text
    assert "badgeBox" in text
    assert "Clutter.BinLayout" in text
    sync = text.split("    _syncIcon(kind) {", 1)[1].split("\n    _", 1)[0]
    assert "kind === 'slash' || kind === 'triangle'" in sync
    assert "face-dot-symbolic" not in sync
    assert "face-ring-symbolic" not in sync
    assert "St.DrawingArea" not in text
    assert "get_foreground_color" not in text
    assert "0.86" not in text
    mark = text.split("    _markDone(row) {", 1)[1].split("\n    _", 1)[0]
    assert "_perform(" not in mark
    assert "shareUndoWindow" in mark
    flush = text.split("    _flushDue(", 1)[1].split("\n    _", 1)[0]
    assert "_perform('done'" in flush
    close = text.split("open-state-changed", 1)[1].split("});", 1)[0]
    assert "menuClosePlan" in close
    assert "_flushDue(true)" not in close
    assert "_undoHolds = []" not in close
    assert "noticeKey" in text.split("    _showNotification(", 1)[1].split("\n    _", 1)[0]
    disable = text.split("    disable() {", 1)[1].split("\n    _buildMenu", 1)[0]
    assert "_flushDue(true)" in disable
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


def test_clipboard_capture_filters_before_it_reads_text():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    capture = text.split("    _captureClipboard() {", 1)[1].split("\n    _", 1)[0]
    assert capture.index("classifyClipboard") < capture.index("get_text")
    assert capture.index("get_text") < capture.index("OfferClipboardRemote")
    assert "OfferClipboardImageRemote" not in capture
    assert "get_content" not in capture
    assert "needs-text" in capture
    assert "_noteClipboard" in capture
    assert "stored-masked" in capture
    assert "NoteClipboardRemote" in text
    image = text.split("    _captureClipboardImage(", 1)[1].split("\n    _", 1)[0]
    assert "get_content" in image
    assert "OfferClipboardImageRemote" in image
    assert "skipped-images-off" in image
    assert "GetClipboardImageRemote" in text
    assert "set_content" in text
    assert "_armClipboardEcho" in text
    assert "clipboard-images" in text
    assert "Could not copy the image" in text
    assert "That image is not available" in text
    menu = text.split("    _buildClipboardIndicator() {", 1)[1].split("\n    _", 1)[0]
    assert "icons/clipboard-symbolic.svg" in menu
    assert "edit-copy-symbolic" not in menu
    assert "icon_size" not in menu
    assert "background-image" not in menu
    assert "accessible_name = 'Clipboard'" in menu
    assert "Clear history" in menu
    assert "text:" not in menu or "count" not in menu
    filled = text.split("    _fillClipboardMenu() {", 1)[1].split("    _installIconTheme()", 1)[0]
    assert "Unpin" in filled
    assert "view-pin-symbolic" in filled
    assert "document-edit-symbolic" in filled
    assert "tetherbot-tag-symbolic" in filled
    assert "tetherbot-clip-actions" in filled
    assert "x_expand: false" in filled
    assert "edit-copy-symbolic" in filled
    assert "background-image" not in filled
    assert "St.Button" in text.split("    _clipIconButton(", 1)[1].split("\n    _", 1)[0]
    assert "system-search-symbolic" in filled
    assert "edit-delete-symbolic" in filled
    assert "EllipsizeMode.END" in filled
    assert "tetherbot-clip-sep" in filled
    assert "line_wrap = false" in filled
    assert "opacity: 0.45" not in filled
    assert "Clutter.EVENT_STOP" in filled
    assert "Images are not edited" in filled
    assert "Images are not searched" in filled
    assert "Images are not sent" in filled
    assert "Hidden passwords are not sent" in filled
    assert "tetherbot-check-symbolic" in filled
    assert "tetherbot-square-check-symbolic" in filled
    assert "tetherbot-circle-help-symbolic" in filled
    assert "clip-todo" in filled
    assert "clip-todo-context" in filled
    assert "clip-ask" in filled
    send = text.split("    _sendClipboard(", 1)[1].split("\n    _", 1)[0]
    assert "SendClipboardRemote" in send
    assert "entry.text" not in send
    assert "entryId, action, 'primary'" in send
    view = (EXTENSION / "view.js").read_text(encoding="utf-8")
    assert "SendClipboardRemote" in view
    assert "tetherbot-clip-thumb" in text
    css = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
    assert ".tetherbot-clip-thumb" in css
    assert ".tetherbot-clip-actions" in css
    assert "width: 220px" not in css
    tag = (
        EXTENSION / "icons" / "hicolor" / "scalable" / "actions" / "tetherbot-tag-symbolic.svg"
    ).read_text(encoding="utf-8")
    assert 'fill="#2e3436"' in tag
    assert "currentColor" not in tag
    assert "stroke" not in tag
    assert "rotate" not in tag
    assert 'd="M9.098,1.017 ' in tag
    assert '<circle cx="5" cy="5" r="1.333" fill="#2e3436"/>' in tag
    notice = (ROOT / "THIRD-PARTY.md").read_text(encoding="utf-8")
    assert "Lucide" in notice
    assert "https://lucide.dev/icons/tag" in notice
    assert "https://lucide.dev/icons/copy" in notice
    assert "Copyright (c) 2026 Lucide Icons and Contributors" in notice
    assert "Permission to use, copy, modify, and/or distribute this software" in notice
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert (
        "For generic UI icons, first use an existing open-licensed icon set such as "
        "Lucide (ISC) or Adwaita symbolic icons. Credit the source in the repo and "
        "convert strokes to filled symbolic paths. Don't draw new icons unless the "
        "icon is specific to TetherBot (for example its face or logo) and the owner "
        "asked for it."
    ) in agents
    assert "PinClipboardRemote" in text
    assert "DeleteClipboardRemote" in text
    assert "SearchClipboardRemote" in text
    assert "launch_default_for_uri" not in text
    assert "'Pinned'" in filled
    assert "clip-edit" in filled


def test_window_icon_is_the_face_and_the_clipboard_icon_wears_it():
    app = (ROOT / "data" / "icons" / "io.github.grokkinggrok.TetherBot.svg").read_text(
        encoding="utf-8"
    )
    symbolic = (
        ROOT / "data" / "icons" / "io.github.grokkinggrok.TetherBot-symbolic.svg"
    ).read_text(encoding="utf-8")
    clip = (EXTENSION / "icons" / "clipboard-symbolic.svg").read_text(encoding="utf-8")
    for icon in (app, symbolic):
        assert icon.count("<circle ") == 2
        assert 'r="1.55"' in icon
        assert "Q8 12.15" in icon
        assert "M8 4V1.6" not in icon
    assert 'fill="#000000"' in app
    assert 'fill="#2e3436"' in symbolic
    assert "currentColor" in clip
    assert "stroke=" not in clip
    assert "stroke-width" not in clip
    assert clip.count("<circle ") == 2
    assert "M5.67 0.67" not in clip
    assert "M2.67 11.33" in clip
    assert 'cx="8.25"' in clip
    assert 'cx="11.75"' in clip
    assert "Q10.00 12.91" in clip
    css = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
    assert "background-image" not in css


def test_the_panel_menu_loads_tetherbot_icons_from_the_extension():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    helper = text.split("    _menuIcon(", 1)[1].split("\n    _", 1)[0]
    assert "startsWith('tetherbot-')" in helper
    assert "icons/hicolor/scalable/actions/" in helper
    assert "Gio.FileIcon.new" in helper
    assert "query_exists" in helper
    assert "icon_name: iconName" in helper
    button = text.split("    _clipIconButton(", 1)[1].split("\n    _", 1)[0]
    assert "_menuIcon(" in button
    assert "_accentPinIcon(" not in button
    assert "icon_size: 16" not in button
    assert "if (accent)" not in button
    assert "color: -st-accent-color" not in button
    assert "reactive: enabled" in button
    assert "track_hover: enabled" in button
    assert "tetherbot-clip-off" in button
    assert "tooltip_text = name" in button
    assert "accessible_name = name" in button
    assert "_accentPinIcon" not in text
    assert "accentPinFile" not in text
    assert "get_accent_color" not in text
    assert "background-image" not in text
    assert "pin-accent-" not in text
    filled = text.split("    _fillClipboardMenu() {", 1)[1].split("    _installIconTheme()", 1)[0]
    assert "tetherbot-tag-symbolic" in filled
    assert "_clipIconButton(" in filled
    assert "view-pin-symbolic" in filled
    assert "'Pinned'" in filled
    assert "'Unpinned'" in filled
    assert "PopupSeparatorMenuItem" in filled
    assert "Nothing copied yet" in filled
    menu = text.split("    _fillClipboardMenu() {", 1)[1].split(
        "    _appendClipboardRows(entries) {", 1
    )[0]
    assert menu.index("'Pinned'") < menu.index("PopupSeparatorMenuItem")
    assert menu.index("PopupSeparatorMenuItem") < menu.index("'Unpinned'")
    assert menu.index("'Unpinned'") < menu.index("Nothing copied yet")
    built = text.split("    _appendClipboardRows(entries) {", 1)[1].split(
        "\n    _installIconTheme()", 1
    )[0]
    assert "Unpinned" not in built
    assert "button-press-event" in built
    assert "clip-edit" in filled
    assert "clip-tag" in filled
    assert "_searchClipboard(" in filled
    assert "MENU_LIMIT" in filled
    assert "opacity:" not in filled
    assert "SearchClipboardRemote" in text
    search = text.split("    _searchClipboard(", 1)[1].split("\n    _", 1)[0]
    assert "SearchClipboardRemote" in search
    assert "launch_default_for_uri" not in search
    css = (EXTENSION / "stylesheet.css").read_text(encoding="utf-8")
    assert ".tetherbot-clip-pin-on StIcon" not in css
    assert ".tetherbot-clip-off" in css
    assert "opacity: 0.35" in css
    assert ".tetherbot-dimmed" in css
    assert "opacity: 0.45" in css


def test_clipboard_send_icons_are_filled_and_credited():
    icons = EXTENSION / "icons" / "hicolor" / "scalable" / "actions"
    check = (icons / "tetherbot-check-symbolic.svg").read_text(encoding="utf-8")
    square = (icons / "tetherbot-square-check-symbolic.svg").read_text(encoding="utf-8")
    help_icon = (icons / "tetherbot-circle-help-symbolic.svg").read_text(encoding="utf-8")
    for blob in (check, square, help_icon):
        assert 'fill="#2e3436"' in blob
        assert "currentColor" not in blob
        assert "stroke" not in blob
        assert "rotate" not in blob
        assert 'viewBox="0 0 16 16"' in blob
    assert check.count("<path") == 1
    assert 'd="M14.04,4.707 ' in check
    assert square.count("<path") == 2
    assert 'd="M3.333,1 ' in square
    assert 'd="M11.374,6.707 ' in square
    assert help_icon.count("<path") == 3
    assert 'd="M15.667,8 ' in help_icon
    assert 'd="M5.117,5.668 ' in help_icon
    assert 'd="M8,10.333 ' in help_icon
    notice = (ROOT / "THIRD-PARTY.md").read_text(encoding="utf-8")
    assert "https://lucide.dev/icons/check" in notice
    assert "https://lucide.dev/icons/square-check" in notice
    assert "https://lucide.dev/icons/circle-question-mark" in notice
    assert "Copyright (c) 2013-present Cole Bemis" in notice
    assert "does not apply to them" in notice


def test_the_menu_undo_bar_is_centered():
    extension = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    needle = (
        "style_class: 'tetherbot-undo-bar',\n"
        "            x_align: Clutter.ActorAlign.CENTER,"
    )
    assert needle in extension


def test_the_desktop_does_not_offer_a_bot_chat_button():
    extension = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    view = (EXTENSION / "view.js").read_text(encoding="utf-8")
    assert "Open chat" not in extension
    assert "Open chat" not in view
    assert "OpenChatRemote" not in extension
    assert "_openChat" not in extension
    assert "botRowCall" in extension
    assert "id: 'open_chat'" not in view

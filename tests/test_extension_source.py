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


def test_disable_drops_the_proxy_and_handlers():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "makeProxyWrapper" in text
    assert "DO_NOT_AUTO_START" in text
    assert "io.github.grokkinggrok.TetherBot1.xml" in text
    disable = text.split("disable()", 1)[1].split("\n    _", 1)[0]
    assert "bus_unwatch_name" in disable
    assert "_dropProxy" in disable
    assert "_source.destroy" in disable
    assert "_indicator?.destroy" in disable
    assert "_proxy = null" in (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "disconnectSignal" in text

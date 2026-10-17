# SPDX-License-Identifier: GPL-2.0-or-later
"""D-Bus session API constants.

``data/io.github.grokkinggrok.TetherBot1.xml`` is the interface source of truth.
The service is not exported yet. Secrets never go on this bus.

The bus name, object path, and interface are frozen. Leave them unchanged
after release. A breaking change bumps the interface to TetherBot2.
"""

from pathlib import Path

BUS_NAME = "io.github.grokkinggrok.TetherBot1"
OBJECT_PATH = "/io/github/grokkinggrok/TetherBot1"
INTERFACE = "io.github.grokkinggrok.TetherBot1"

STATES = (
    "unconfigured",
    "ok",
    "degraded",
    "offline",
    "failed_closed",
    "paused",
)


def interface_xml_path() -> Path:
    """Return the introspection XML path in a source checkout."""

    return Path(__file__).resolve().parents[2] / "data" / "io.github.grokkinggrok.TetherBot1.xml"


def interface_xml() -> str:
    return interface_xml_path().read_text(encoding="utf-8")

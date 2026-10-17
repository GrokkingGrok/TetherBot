# SPDX-License-Identifier: GPL-2.0-or-later
"""D-Bus session API constants.

``data/org.tetherbot.Bridge1.xml`` is the interface source of truth.
The service is not exported yet. Secrets never go on this bus.

TODO: confirm ``BUS_NAME`` before v0.2. Leave it unchanged after release.
"""

from pathlib import Path

BUS_NAME = "org.tetherbot.Bridge1"
OBJECT_PATH = "/org/tetherbot/Bridge1"
INTERFACE = "org.tetherbot.Bridge1"

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

    return Path(__file__).resolve().parents[2] / "data" / "org.tetherbot.Bridge1.xml"


def interface_xml() -> str:
    return interface_xml_path().read_text(encoding="utf-8")

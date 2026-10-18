# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke test: the fake adapter reads a fixture and records an outbound batch."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tetherbot import SCHEMA_VERSION, __version__
from tetherbot.adapters.fake import FakeAdapter
from tetherbot.dbus_service import (
    BUS_NAME,
    INTERFACE,
    OBJECT_PATH,
    interface_xml,
    interface_xml_path,
)
from tetherbot.model import ActionEnvelope

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fake"


def test_schema_constant():
    assert SCHEMA_VERSION == "tetherbot/1"


def test_fake_adapter_poll_and_send():
    adapter = FakeAdapter(FIXTURES)
    adapter.start(None)
    result = adapter.poll()
    assert result.errors == []
    assert result.stale_sources == []
    assert len(result.items) == 1
    item = result.items[0]
    assert item.key == "primary/primary-20261017-01"
    assert item.origin == "fake"
    assert item.extra["example_extra"] is True

    envelope = ActionEnvelope(
        schema=SCHEMA_VERSION,
        type="actions",
        batch_id="b-example",
        sent_at="2026-10-17T12:00:00+00:00",
        actions=[
            {
                "action_id": "a-example",
                "item": item.key,
                "action": "approve",
                "args": {},
                "created": "2026-10-17T12:00:00+00:00",
            }
        ],
        client={"name": "tetherbot", "version": __version__},
    )
    sent = adapter.send("primary", [envelope])
    assert sent.status == "accepted"
    assert adapter.sent == [("primary", [envelope])]
    adapter.stop()
    assert adapter.status().state == "stopped"


def test_fake_adapter_fails_closed_on_unknown_major(tmp_path: Path):
    future = {
        "schema": "tetherbot/2",
        "bot": "primary",
        "items": [{"id": "later", "kind": "ask", "title": "ignored"}],
    }
    (tmp_path / "future.json").write_text(json.dumps(future), encoding="utf-8")
    minor = {
        "schema": "tetherbot/1.2",
        "bot": "primary",
        "items": [
            {
                "id": "minor-ok",
                "kind": "todo",
                "title": "Still readable",
                "created": "2026-10-17T11:40:00+00:00",
                "updated_at": "2026-10-17T11:40:00+00:00",
                "source": {"bot": "primary"},
            }
        ],
    }
    (tmp_path / "minor.json").write_text(json.dumps(minor), encoding="utf-8")

    result = FakeAdapter(tmp_path).poll()
    assert [item.key for item in result.items] == ["primary/minor-ok"]
    assert result.stale_sources == ["future.json"]
    assert any("unsupported schema tetherbot/2" in error for error in result.errors)


def test_dbus_interface_xml_names_the_bus():
    assert BUS_NAME == "io.github.grokkinggrok.TetherBot1"
    assert INTERFACE == BUS_NAME
    assert OBJECT_PATH == "/io/github/grokkinggrok/TetherBot1"
    assert interface_xml_path().name == "io.github.grokkinggrok.TetherBot1.xml"
    root = ET.fromstring(interface_xml())
    interface = root.find("interface")
    assert interface is not None
    assert interface.attrib["name"] == INTERFACE
    names = {method.attrib["name"] for method in interface.findall("method")}
    assert "PerformAction" in names
    assert "RequestSecretEntry" in names

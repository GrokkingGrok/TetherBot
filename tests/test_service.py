# SPDX-License-Identifier: GPL-2.0-or-later
"""Session API over the store and queue, without a bus connection."""

import json
import stat
import xml.etree.ElementTree as ET
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import NOW, make_item
from tetherbot.daemon import BridgeDaemon
from tetherbot.dbus_service import interface_xml
from tetherbot.service import METHOD_OUT, PROPERTY_TYPES, ServiceError


def _daemon(tmp_path: Path, config: str | None = None) -> BridgeDaemon:
    if config is not None:
        (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    return BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        clock=lambda: NOW,
    )


def _api(tmp_path: Path, config: str | None = None) -> tuple[BridgeDaemon, list]:
    daemon = _daemon(tmp_path, config)
    daemon.start()
    assert daemon.api is not None
    seen: list = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    return daemon, seen


def test_xml_matches_the_implemented_api():
    root = ET.fromstring(interface_xml())
    interface = root.find("interface")
    assert interface is not None
    methods = {node.attrib["name"] for node in interface.findall("method")}
    properties = {node.attrib["name"] for node in interface.findall("property")}
    assert methods == set(METHOD_OUT)
    assert properties == set(PROPERTY_TYPES)


def test_properties_and_filtered_items(tmp_path: Path):
    daemon, _seen = _api(tmp_path, 'schema = "tetherbot/1"\n[bridge]\nmode = "webhook-only"\n')
    assert daemon.store is not None
    daemon.store.replace_origin(
        "feed",
        [
            make_item(),
            make_item(
                id="other-01",
                bot="other",
                kind="todo",
                actions=["done"],
                source={"bot": "other"},
            ),
        ],
        now=NOW,
    )
    api = daemon.api
    assert api is not None
    props = api.properties()
    assert props["Version"] == "0.0.0"
    assert props["ProtocolVersions"] == ["tetherbot/1"]
    assert props["State"] == "unconfigured"
    assert props["Mode"] == "webhook-only"
    assert props["LastSync"] == 0
    assert props["QueueLength"] == 0
    assert props["Counts"]["asks"] == 1
    assert props["Counts"]["todos"] == 1
    assert props["Counts"]["queued"] == 0
    bots = json.loads(props["Bots"])
    assert [row["name"] for row in bots] == ["other", "primary"]
    items = json.loads(api.call("GetItems", ('{"kinds":["ask"]}',))[0])
    assert [row["key"] for row in items] == ["primary/sample-01"]
    assert items[0]["local"]["seen"] is False
    with pytest.raises(ServiceError, match="unknown filter key") as caught:
        api.call("GetItems", ('{"nope":true}',))
    assert caught.value.error_name.endswith(".Error.InvalidArgs")


def test_get_item_missing_and_perform_action(tmp_path: Path):
    daemon, seen = _api(tmp_path)
    assert daemon.store is not None and daemon.api is not None and daemon.queue is not None
    daemon.store.replace_origin("feed", [make_item()], now=NOW)
    api = daemon.api
    with pytest.raises(ServiceError, match="item not found") as missing:
        api.call("GetItem", ("primary/missing-01",))
    assert missing.value.error_name.endswith(".Error.NotFound")
    action_id = api.call("PerformAction", ("primary/sample-01", "approve", "{}"))[0]
    assert daemon.queue.pending_count() == 1
    assert api.properties()["QueueLength"] == 1
    assert api.properties()["Counts"]["queued"] == 1
    assert seen[-1][0] == "PropertiesChanged"
    assert (tmp_path / "state" / "queue" / f"{action_id}.json").is_file()
    with pytest.raises(ServiceError, match="not listed"):
        api.call("PerformAction", ("primary/sample-01", "veto", "{}"))
    assert daemon.queue.pending_count() == 1
    with pytest.raises(ServiceError, match="snooze is local"):
        api.call("PerformAction", ("primary/sample-01", "snooze", "{}"))


def test_snooze_hides_the_item_and_mark_seen(tmp_path: Path):
    daemon, seen = _api(tmp_path)
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin("feed", [make_item(notify=False)], now=NOW)
    until = (NOW + timedelta(hours=1)).isoformat()
    assert daemon.api.call("Snooze", ("primary/sample-01", until)) == (True,)
    visible = json.loads(daemon.api.call("GetItems", ("{}",))[0])
    assert visible == []
    hidden = json.loads(daemon.api.call("GetItems", ('{"include_snoozed":true}',))[0])
    assert hidden[0]["local"]["snoozed_until"] == until
    assert ("ItemsChanged", ([], ["primary/sample-01"], [])) in seen
    daemon.api.call("MarkSeen", (["primary/sample-01", "missing/nope"],))
    stored = daemon.store.get("primary/sample-01")
    assert stored is not None and stored.seen is True
    assert daemon.api.call("Snooze", ("missing/nope", until)) == (False,)


def test_send_to_bot_and_queue_management(tmp_path: Path):
    daemon, _seen = _api(tmp_path)
    assert daemon.api is not None and daemon.queue is not None
    payload = {
        "schema": "tetherbot/1",
        "type": "actions",
        "actions": [
            {
                "action_id": "a-run1",
                "item": "primary/run-now",
                "action": "run_now",
                "args": {},
            }
        ],
    }
    assert daemon.api.call("SendToBot", ("primary", json.dumps(payload))) == ("a-run1",)
    secret = "ghp_abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(ServiceError, match="looks like a secret") as caught:
        daemon.api.call(
            "SendToBot",
            (
                "primary",
                json.dumps({"action": "note", "item": "primary/x", "args": {"text": secret}}),
            ),
        )
    assert secret not in str(caught.value)
    daemon.queue.park("a-run1", "waiting")
    assert daemon.api.properties()["QueueLength"] == 0
    queued = json.loads(daemon.api.call("GetQueue", ())[0])
    assert queued[0]["state"] == "parked"
    daemon.api.call("RetryParked", ("a-run1",))
    assert daemon.api.properties()["QueueLength"] == 1
    daemon.api.call("DropQueued", ("a-run1",))
    assert daemon.api.properties()["QueueLength"] == 0
    with pytest.raises(ServiceError, match="not in the queue"):
        daemon.api.call("DropQueued", ("a-run1",))


def test_sync_is_rate_limited_and_open_chat_does_not_launch(tmp_path: Path):
    daemon, _seen = _api(tmp_path)
    assert daemon.api is not None
    daemon.api.call("SyncNow", ())
    daemon.api.call("SyncNow", ())
    assert daemon.api.properties()["LastSync"] == 0
    assert daemon.api.call("OpenChat", ("primary",)) == (False,)


def test_set_adapter_enabled_rewrites_config_and_state(tmp_path: Path):
    config = (
        'schema = "tetherbot/1"\n\n'
        "[bridge]\nmode = \"full\"\n\n"
        "[adapters.webhook-sender]\nenabled = false\n"
    )
    daemon, seen = _api(tmp_path, config)
    assert daemon.api is not None
    daemon.api.call("SetAdapterEnabled", ("webhook-sender", True))
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "enabled = true" in text
    assert stat.S_IMODE((tmp_path / "config.toml").stat().st_mode) == 0o600
    assert daemon.state == "ok"
    assert daemon.reason == ""
    assert ("StateChanged", ("ok", "")) in seen
    adapters = json.loads(daemon.api.call("GetAdapters", ())[0])
    webhook = next(row for row in adapters if row["name"] == "webhook-sender")
    assert webhook["enabled"] is True
    assert webhook["state"] == "running"
    assert webhook["version_gate"] == "routine-webhook-2026-10"
    with pytest.raises(ServiceError, match="unknown adapter"):
        daemon.api.call("SetAdapterEnabled", ("carrier-pigeon", True))
    assert daemon.api.call("RequestSecretEntry", ("primary-actions",)) == (False,)
    with pytest.raises(ServiceError, match="slot is not a name") as leaked:
        daemon.api.call("ForgetSecret", ("ghp_abcdefghijklmnopqrstuvwxyz",))
    assert "ghp_" not in str(leaked.value)


def test_enabling_a_missing_section_appends_it(tmp_path: Path):
    daemon, _seen = _api(tmp_path, 'schema = "tetherbot/1"\n[bridge]\nmode = "full"\n')
    assert daemon.api is not None
    daemon.api.call("SetAdapterEnabled", ("official", True))
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "[adapters.official]\nenabled = true\n" in text
    assert daemon.reason == "not started: official"


def test_missing_config_cannot_enable_an_adapter(tmp_path: Path):
    daemon, _seen = _api(tmp_path)
    assert daemon.api is not None
    with pytest.raises(ServiceError, match="config.toml is missing"):
        daemon.api.call("SetAdapterEnabled", ("webhook-sender", True))
    assert not (tmp_path / "config.toml").exists()

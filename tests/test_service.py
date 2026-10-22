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
    assert props["Version"] == "0.1.0"
    assert props["ProtocolVersions"] == ["tetherbot/1"]
    assert props["State"] == "unconfigured"
    assert props["Mode"] == "webhook-only"
    assert props["LastSync"] == 0
    assert props["QueueLength"] == 0
    assert props["Counts"]["asks"] == 1
    assert props["Counts"]["todos"] == 1
    assert props["Counts"]["queued"] == 0
    bots = json.loads(props["Bots"])
    assert [row["name"] for row in bots] == ["primary", "other"]
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


def test_sync_now_forces_one_poll(tmp_path: Path):
    daemon, seen = _api(tmp_path)
    assert daemon.api is not None
    calls: list[bool] = []

    def tick(*, force: bool = False) -> None:
        calls.append(force)

    daemon.poller = type("Poller", (), {"tick": staticmethod(tick)})()
    daemon.api.call("SyncNow", ())
    daemon.api.call("SyncNow", ())
    assert calls == [True]
    assert daemon.api.properties()["LastSync"] == int(NOW.timestamp())
    assert ("PropertiesChanged", (("LastSync",),)) in seen


def test_a_bot_without_a_slot_does_not_fail_the_bridge(tmp_path: Path):
    daemon, _seen = _api(
        tmp_path,
        "\n".join(
            [
                'schema = "tetherbot/1"',
                "[bridge]",
                'mode = "full"',
                "[adapters.webhook-sender]",
                "enabled = true",
                "[bots.primary]",
                'webhook_slot = "primary-actions"',
                "[bots.notes]",
                'display_name = "Notes"',
                "[bots.other]",
                'webhook_slot = "NOT A SLOT"',
            ]
        ),
    )
    assert daemon.state == "ok"
    assert daemon.api is not None
    bots = {row["name"]: row for row in json.loads(daemon.api.properties()["Bots"])}
    assert bots["notes"]["routes"]["outbound"] is False
    assert bots["notes"]["display_name"] == "Notes"
    assert bots["primary"]["routes"]["outbound"] is True
    assert bots["other"]["routes"]["outbound"] is False
    assert bots["other"]["state"] == "error"
    assert bots["other"]["summary"] == "webhook slot was rejected"
    assert "NOT A SLOT" not in json.dumps(bots)


def test_created_chip_uses_the_desktop_zone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from datetime import timedelta, timezone

    pacific = timezone(timedelta(hours=-7))
    monkeypatch.setattr("tetherbot.service.display_zone", lambda: pacific)
    daemon, _seen = _api(tmp_path)
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed",
        [make_item(kind="todo", actions=["done"], created="2026-10-20T04:40:50+00:00")],
        now=NOW,
    )
    rows = json.loads(daemon.api.call("GetItems", ('{"kinds":["todo"]}',))[0])
    assert rows[0]["chips"]["created"]["label"] == "Created Oct 19"


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


def test_settings_hide_bots_and_keys_stay_off_the_bus(tmp_path: Path):
    from tetherbot.secrets import MemoryBackend, SecretStore
    from tetherbot.ui_settings import UiSettings

    secrets = SecretStore(MemoryBackend())
    secrets.put_webhook("primary-actions", "https://hooks.example/hook", "super-secret-key")
    config = "\n".join(
        [
            'schema = "tetherbot/1"',
            "[bridge]",
            'mode = "full"',
            "[bots.primary]",
            'webhook_slot = "primary-actions"',
            "[bots.notes]",
            'webhook_slot = "notes-actions"',
        ]
    )
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        clock=lambda: NOW,
        secrets=secrets,
    )
    daemon.start()
    assert daemon.store is not None and daemon.api is not None
    daemon.store.replace_origin(
        "feed",
        [
            make_item(),
            make_item(
                id="notes-01",
                bot="notes",
                kind="todo",
                actions=["done"],
                source={"bot": "notes"},
            ),
        ],
        now=NOW,
    )
    api = daemon.api
    raw = api.call("GetSetup", ())[0]
    assert "super-secret-key" not in raw
    assert "https://hooks.example/hook" not in raw
    setup = json.loads(raw)
    primary = next(slot for slot in setup["slots"] if slot["slot"] == "primary-actions")
    notes = next(slot for slot in setup["slots"] if slot["slot"] == "notes-actions")
    token = next(slot for slot in setup["slots"] if slot["slot"] == "github-token")
    assert primary["stored"] is True
    assert primary["kind"] == "webhook"
    assert notes["stored"] is False
    assert token["stored"] is False
    assert "key" not in primary
    assert "url" not in primary
    assert setup["poll_seconds"] is None

    daemon.ui_settings = UiSettings(hidden_bots=frozenset({"notes"}))
    items = json.loads(api.call("GetItems", ("{}",))[0])
    assert [row["key"] for row in items] == ["primary/sample-01"]
    bots = [row["name"] for row in json.loads(api.properties()["Bots"])]
    assert bots == ["primary"]
    with pytest.raises(ServiceError, match="item not found"):
        api.call("GetItem", ("notes/notes-01",))
    api.call("ReloadSettings", ())
    assert [row["name"] for row in json.loads(api.properties()["Bots"])] == ["primary"]

    seen: list = []
    api.subscribe(lambda name, args: seen.append((name, args)))
    daemon.ui_settings = UiSettings(muted_bots=frozenset({"primary"}))
    api.emit_notification('{"source":{"bot":"primary"},"title":"Hello"}', "new")
    api.emit_notification('{"bot":"notes","title":"Still here"}', "delivery_failed")
    notices = [item for item in seen if item[0] == "NotificationRequested"]
    assert len(notices) == 1
    assert "notes" in notices[0][1][0]
    assert "Hello" not in notices[0][1][0]

    opened: list[str] = []
    daemon.launch_secret_dialog = lambda slot: opened.append(slot) or True
    assert api.call("RequestSecretEntry", ("primary-actions",)) == (True,)
    assert opened == ["primary-actions"]


def test_setup_reports_the_configured_poll_interval(tmp_path: Path):
    daemon, _seen = _api(
        tmp_path,
        "\n".join(
            [
                'schema = "tetherbot/1"',
                "[bridge]",
                'mode = "webhook-only"',
                "[adapters.github-poller]",
                "enabled = false",
                "poll_seconds = 180",
            ]
        ),
    )
    assert daemon.api is not None
    setup = json.loads(daemon.api.call("GetSetup", ())[0])
    assert setup["poll_seconds"] == 180


def test_done_with_note_is_queued_and_plain_done_stays_empty(tmp_path: Path):
    daemon, _seen = _api(tmp_path)
    assert daemon.store is not None and daemon.api is not None and daemon.queue is not None
    daemon.store.replace_origin(
        "feed",
        [
            make_item(id="todo-01", kind="todo", title="Pack the bag", actions=["done"]),
            make_item(id="todo-02", kind="todo", title="Mail the form", actions=["done"]),
            make_item(id="todo-03", kind="todo", title="File the form", actions=["done"]),
            make_item(),
        ],
        now=NOW,
    )
    api = daemon.api
    noted = api.call(
        "PerformAction",
        ("primary/todo-01", "done", json.dumps({"note": "  Packed the blue bag  "})),
    )[0]
    queued = {row.action_id: row for row in daemon.queue.snapshot()}
    assert queued[noted].action == "done"
    assert queued[noted].args == {"note": "Packed the blue bag"}
    plain = api.call("PerformAction", ("primary/todo-02", "done", "{}"))[0]
    assert daemon.queue.snapshot()
    queued = {row.action_id: row for row in daemon.queue.snapshot()}
    assert queued[plain].args == {}
    with pytest.raises(ServiceError, match="1 to 500"):
        api.call(
            "PerformAction",
            ("primary/todo-03", "done", json.dumps({"note": "x" * 501})),
        )
    with pytest.raises(ServiceError, match="does not take arguments"):
        api.call("PerformAction", ("primary/sample-01", "approve", json.dumps({"note": "no"})))


def test_missing_config_cannot_enable_an_adapter(tmp_path: Path):
    daemon, _seen = _api(tmp_path)
    assert daemon.api is not None
    with pytest.raises(ServiceError, match="config.toml is missing"):
        daemon.api.call("SetAdapterEnabled", ("webhook-sender", True))
    assert not (tmp_path / "config.toml").exists()

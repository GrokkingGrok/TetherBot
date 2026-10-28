# SPDX-License-Identifier: GPL-2.0-or-later
"""Hide approve, veto, and done on tap, then close them through state.json."""

import json
from datetime import timedelta
from io import StringIO
from pathlib import Path

from tests.helpers import NOW, make_item
from tests.test_github_poller import (
    KEY,
    _bare,
    _clone,
    _feed,
    _git,
    _push,
    _seed,
    _write_json,
)
from tetherbot.adapters.webhook_sender import HttpOutcome, plan_for
from tetherbot.daemon import BridgeDaemon
from tetherbot.secrets import MemoryBackend, SecretStore
from tetherbot.store import ItemStore

WEBHOOK_URL = "https://example.test/hook/primary"
WEBHOOK_KEY = "desk-hook-key"
_CONFIG = """\
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[adapters.webhook-sender]
enabled = true

[bots.primary]
webhook_slot = "primary-actions"
"""


class Clock:
    def __init__(self) -> None:
        self.moment = NOW

    def __call__(self):
        return self.moment


class Script:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def __call__(self, url: str, key: str, body: bytes) -> HttpOutcome:
        del url, key
        self.calls.append(json.loads(body))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, HttpOutcome):
            return outcome
        return HttpOutcome("status", int(outcome))


def _boot(tmp_path: Path, script: Script, *, config: str = _CONFIG) -> tuple[BridgeDaemon, Clock]:
    clock = Clock()
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        repos_dir=tmp_path / "repos",
        log_stream=StringIO(),
        clock=clock,
        secrets=SecretStore(MemoryBackend()),
        webhook_post=script,
        webhook_jitter=lambda _delay: 0,
    )
    daemon.start()
    assert daemon.api is not None and daemon.store is not None
    daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    daemon.store.replace_origin(
        "feed",
        [make_item(actions=["approve", "veto", "done"], due=None)],
        now=NOW,
    )
    return daemon, clock


def _keys(daemon: BridgeDaemon) -> list[str]:
    assert daemon.api is not None
    rows = json.loads(daemon.api.call("GetItems", ("{}",))[0])
    return [row["key"] for row in rows]


def _send(daemon: BridgeDaemon, clock: Clock) -> None:
    clock.moment = NOW + timedelta(seconds=20)
    daemon.tick_webhook()


def test_enqueue_hides_the_item_and_keeps_it_in_the_queue(tmp_path: Path):
    daemon, _clock = _boot(tmp_path, Script([200]))
    assert daemon.api is not None
    action_id = daemon.api.call("PerformAction", ("primary/sample-01", "veto", "{}"))[0]
    assert _keys(daemon) == []
    assert daemon.api.properties()["Counts"]["asks"] == 0
    assert daemon.api.properties()["QueueLength"] == 1
    stored = daemon.store.get("primary/sample-01")
    assert stored is not None
    assert stored.status == "open"
    assert stored.acted == {
        "action": "veto",
        "action_id": action_id,
        "at": NOW.isoformat(),
    }
    shown = json.loads(daemon.api.call("GetItem", ("primary/sample-01",))[0])
    assert shown["local"]["acted"]["action"] == "veto"
    assert WEBHOOK_KEY not in json.dumps(shown)


def test_retry_stays_hidden_and_park_or_reject_shows_the_item(tmp_path: Path):
    retrying, clock = _boot(tmp_path, Script([400]))
    assert retrying.api is not None
    retrying.api.call("PerformAction", ("primary/sample-01", "done", "{}"))
    _send(retrying, clock)
    shown = json.loads(retrying.api.call("GetItems", ("{}",))[0])
    assert [row["key"] for row in shown] == ["primary/sample-01"]
    assert shown[0]["local"]["sending"] == "retry"
    assert retrying.api.properties()["QueueLength"] == 1
    row = retrying.queue.snapshot()[0]
    assert row.state == "pending"

    parked, parked_clock = _boot(tmp_path / "park", Script([HttpOutcome("timeout")] * 2))
    assert parked.api is not None
    seen: list[tuple[str, tuple]] = []
    parked.api.subscribe(lambda name, payload: seen.append((name, payload)))
    parked.api.call("PerformAction", ("primary/sample-01", "approve", "{}"))
    _send(parked, parked_clock)
    parked_clock.moment = NOW + timedelta(minutes=3)
    parked.tick_webhook()
    assert parked.queue.snapshot()[0].state == "parked"
    assert _keys(parked) == ["primary/sample-01"]
    assert parked.api.properties()["Counts"]["asks"] == 1
    assert parked.api.properties()["QueueLength"] == 0
    assert any(
        item[0] == "NotificationRequested" and item[1][1] == "delivery_failed" for item in seen
    )

    rejected, _rejected_clock = _boot(tmp_path / "reject", Script([401]))
    assert rejected.api is not None
    rejected.api.call("PerformAction", ("primary/sample-01", "veto", "{}"))
    _send(rejected, _rejected_clock)
    assert _keys(rejected) == ["primary/sample-01"]
    assert rejected.store.get("primary/sample-01").acted is None
    assert rejected.reason == "re-paste key"


def test_pending_done_stays_until_accept_and_returns_after_park(tmp_path: Path):
    staying, _clock = _boot(tmp_path, Script([500]))
    assert staying.api is not None and staying.queue is not None
    action_id = staying.api.call("PerformAction", ("primary/sample-01", "done", "{}"))[0]
    assert staying.api.call("PerformAction", ("primary/sample-01", "done", "{}"))[0] == action_id
    assert len([row for row in staying.queue.snapshot() if row.action == "done"]) == 1
    shown = json.loads(staying.api.call("GetItems", ("{}",))[0])
    assert shown[0]["key"] == "primary/sample-01"
    assert shown[0]["local"]["sending"] == "retry"

    accepted, accepted_clock = _boot(tmp_path / "accept", Script([200]))
    assert accepted.api is not None
    accepted.api.call("PerformAction", ("primary/sample-01", "done", "{}"))
    assert _keys(accepted) == ["primary/sample-01"]
    _send(accepted, accepted_clock)
    assert _keys(accepted) == []

    parked, parked_clock = _boot(tmp_path / "park", Script([HttpOutcome("timeout")] * 2))
    assert parked.api is not None and parked.queue is not None
    first = parked.api.call("PerformAction", ("primary/sample-01", "done", "{}"))[0]
    _send(parked, parked_clock)
    parked_clock.moment = NOW + timedelta(minutes=3)
    parked.tick_webhook()
    assert parked.queue.snapshot()[0].state == "parked"
    returned = json.loads(parked.api.call("GetItems", ("{}",))[0])
    assert [row["key"] for row in returned] == ["primary/sample-01"]
    assert returned[0]["local"].get("sending") != "retry"
    second = parked.api.call("PerformAction", ("primary/sample-01", "done", "{}"))[0]
    assert second != first
    pending = [
        row for row in parked.queue.snapshot() if row.action == "done" and row.state == "pending"
    ]
    assert len(pending) == 1


def test_accept_resolves_and_a_duplicate_stays_resolved(tmp_path: Path):
    daemon, clock = _boot(tmp_path, Script([200]))
    assert daemon.api is not None and daemon.store is not None
    daemon.api.call("PerformAction", ("primary/sample-01", "approve", "{}"))
    _send(daemon, clock)
    stored = daemon.store.get("primary/sample-01")
    assert stored is not None
    assert stored.status == "open"
    assert stored.resolved == "done"
    assert stored.acted is not None and stored.acted["action"] == "approve"
    assert _keys(daemon) == []
    assert daemon.api.properties()["QueueLength"] == 0
    accepted_204 = plan_for(HttpOutcome("status", 204), timeout_retry=False, attempts=1)
    accepted_409 = plan_for(HttpOutcome("status", 409), timeout_retry=False, attempts=1)
    assert accepted_204.result == "accepted"
    assert accepted_409.result == "accepted"

    duplicate, duplicate_clock = _boot(tmp_path / "dup", Script([409]))
    assert duplicate.api is not None
    duplicate.api.call("PerformAction", ("primary/sample-01", "veto", "{}"))
    _send(duplicate, duplicate_clock)
    vetoed = duplicate.store.get("primary/sample-01")
    assert vetoed is not None
    assert vetoed.resolved == "dropped"
    assert _keys(duplicate) == []


def test_resolved_item_survives_a_restart(tmp_path: Path):
    daemon, clock = _boot(tmp_path, Script([200]))
    assert daemon.api is not None
    daemon.api.call("PerformAction", ("primary/sample-01", "veto", "{}"))
    _send(daemon, clock)
    daemon.stop()
    restarted = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        clock=Clock(),
    )
    restarted.start()
    assert restarted.api is not None and restarted.store is not None
    assert _keys(restarted) == []
    stored = restarted.store.get("primary/sample-01")
    assert stored is not None
    assert stored.resolved == "dropped"
    assert stored.acted is not None
    assert restarted.api.properties()["Counts"]["asks"] == 0


def test_newer_open_feed_reopens_and_a_closed_feed_stays_hidden():
    store = ItemStore()
    acted_at = NOW.isoformat()
    store.replace_origin("feed", [make_item(actions=["veto"], due=None)], now=NOW)
    assert store.record_action("primary/sample-01", "veto", "a-veto1", NOW)
    same = store.replace_origin("feed", [make_item(actions=["veto"], due=None)], now=NOW)
    assert same.notifications == ()
    assert store.get("primary/sample-01").acted["at"] == acted_at

    reopened = store.replace_origin(
        "feed",
        [make_item(actions=["veto"], due=None, updated_at="2026-10-17T13:00:00+00:00")],
        now=NOW + timedelta(hours=1),
    )
    assert store.get("primary/sample-01").acted is None
    assert store.get("primary/sample-01").resolved is None
    assert store.get("primary/sample-01").status == "open"
    assert store.counts(now=NOW + timedelta(hours=1))["asks"] == 1
    assert [notice.reason for notice in reopened.notifications] == ["changed"]

    assert store.record_action("primary/sample-01", "veto", "a-veto2", NOW + timedelta(hours=2))
    dropped = store.replace_origin(
        "feed",
        [
            make_item(
                actions=["veto"],
                due=None,
                status="dropped",
                updated_at="2026-10-17T14:00:00+00:00",
            )
        ],
        now=NOW + timedelta(hours=2),
    )
    hidden = store.get("primary/sample-01")
    assert hidden is not None
    assert hidden.status == "dropped"
    assert hidden.acted is None
    assert store.counts(now=NOW + timedelta(hours=2))["asks"] == 0
    assert dropped.notifications == ()


def test_write_back_pushes_state_and_does_not_touch_the_feed(tmp_path: Path):
    remote = _seed(tmp_path)
    script = Script([200])
    clock = Clock()
    config = "\n".join(
        [
            'schema = "tetherbot/1"',
            "[bridge]",
            'mode = "full"',
            "[adapters.github-poller]",
            "enabled = true",
            f'remote = "{remote}"',
            'branch = "main"',
            "poll_seconds = 60",
            "[adapters.webhook-sender]",
            "enabled = true",
            "[bots.primary]",
            'webhook_slot = "primary-actions"',
            "",
        ]
    )
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        repos_dir=tmp_path / "repos",
        log_stream=StringIO(),
        clock=clock,
        secrets=SecretStore(MemoryBackend()),
        webhook_post=script,
        webhook_jitter=lambda _delay: 0,
    )
    daemon.start()
    assert daemon.api is not None and daemon.store is not None
    daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    daemon.tick_poller()
    clone = _clone(daemon)
    feed_bytes = (clone / "feed" / "primary.json").read_bytes()
    assert KEY in _keys(daemon)

    daemon.api.call("PerformAction", (KEY, "veto", "{}"))
    assert _keys(daemon) == []
    assert daemon.api.properties()["QueueLength"] == 1
    clock.moment = NOW + timedelta(seconds=20)
    daemon.tick_webhook()
    assert daemon.store.get(KEY).resolved == "dropped"
    assert daemon.api.properties()["QueueLength"] == 0
    assert (clone / "feed" / "primary.json").read_bytes() == feed_bytes

    clock.moment = NOW + timedelta(seconds=60)
    daemon.tick_poller()
    state = json.loads((clone / "desktop" / "state.json").read_text(encoding="utf-8"))
    entry = next(row for row in state["items"] if row["key"] == KEY)
    assert entry["status"] == "dropped"
    assert entry["acted"]["action"] == "veto"
    assert entry["acted"]["action_id"]
    assert (clone / "feed" / "primary.json").read_bytes() == feed_bytes
    owned = _git(clone, "log", "--author=TetherBot", "--name-only", "--pretty=format:")
    assert "feed/" not in owned.stdout
    assert "desktop/state.json" in owned.stdout
    assert "feed/" not in _git(clone, "status", "--porcelain").stdout

    other = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "other-state",
        repos_dir=tmp_path / "other-repos",
        log_stream=StringIO(),
        clock=clock,
        secrets=SecretStore(MemoryBackend()),
    )
    other.start()
    other.tick_poller()
    assert other.store is not None
    assert _keys(other) == []
    assert other.store.get(KEY).resolved == "dropped"
    assert (other.repos_dir / "repo" / "feed" / "primary.json").read_bytes() == feed_bytes

    daemon.stop()
    restarted = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        repos_dir=tmp_path / "repos",
        log_stream=StringIO(),
        clock=clock,
    )
    restarted.start()
    assert _keys(restarted) == []

    def writer(side: Path) -> None:
        payload = _feed()
        payload["items"][0]["updated_at"] = "2026-10-17T13:00:00+00:00"
        _write_json(side / "feed" / "primary.json", payload)

    _push(tmp_path, _bare(remote), "bot edits the ask", writer)
    clock.moment = NOW + timedelta(seconds=180)
    restarted.tick_poller()
    assert KEY in _keys(restarted)
    restored = restarted.store.get(KEY)
    assert restored is not None
    assert restored.acted is None
    assert restored.resolved is None
    assert restored.status == "open"
    bridge_paths = _git(
        _clone(restarted),
        "log",
        "--author=TetherBot",
        "--name-only",
        "--pretty=format:",
    )
    assert "feed/" not in bridge_paths.stdout

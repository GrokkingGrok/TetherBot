# SPDX-License-Identifier: GPL-2.0-or-later
"""webhook-sender: bearer POST, retry table, and re-paste, with no network."""

import json
import os
import subprocess
import sys
import urllib.error
from datetime import timedelta
from io import StringIO
from pathlib import Path

from tests.helpers import NOW, make_item
from tetherbot import __version__
from tetherbot.adapters.webhook_sender import (
    PROFILE,
    HttpOutcome,
    _NoRedirect,
    plan_for,
    post_json,
)
from tetherbot.daemon import BridgeDaemon
from tetherbot.model import parse_iso8601
from tetherbot.secrets import MemoryBackend, SecretStore

ROOT = Path(__file__).resolve().parents[1]
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


class Script:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def __call__(self, url: str, key: str, body: bytes) -> HttpOutcome:
        self.calls.append((url, key, json.loads(body)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, HttpOutcome):
            return outcome
        return HttpOutcome("status", int(outcome))


class Clock:
    def __init__(self) -> None:
        self.moment = NOW

    def __call__(self):
        return self.moment


def test_accept_posts_one_bearer_batch_and_records_a_poll_burst(tmp_path: Path):
    script = Script([200])
    daemon, _clock, seen, log = _boot(tmp_path, script)
    assert daemon.store is not None
    daemon.store.replace_origin("feed", [make_item()], now=NOW)
    _enqueue(daemon, "a-ok1", NOW - timedelta(seconds=30))
    _enqueue(daemon, "a-ok2", NOW - timedelta(seconds=25))
    daemon.tick_webhook()
    assert len(script.calls) == 1
    url, key, body = script.calls[0]
    assert url == WEBHOOK_URL
    assert key == WEBHOOK_KEY
    assert body["schema"] == "tetherbot/1"
    assert body["type"] == "actions"
    assert body["client"] == {"host": "desktop", "name": "tetherbot", "version": __version__}
    assert __version__ == "0.1.0"
    actions = body["actions"]
    assert [row["action_id"] for row in actions] == ["a-ok1", "a-ok2"]
    assert actions[0]["title"] == "Approve the sample"
    assert actions[0]["kind"] == "ask"
    assert ("PropertiesChanged", (("QueueLength", "Counts"),)) in seen
    assert daemon.api.properties()["QueueLength"] == 0
    assert WEBHOOK_KEY not in json.dumps(body)
    assert daemon.queue.snapshot() == ()
    assert ("ActionResult", ("a-ok1", "accepted", "")) in seen
    assert ("ActionResult", ("a-ok2", "accepted", "")) in seen
    burst = [item.isoformat() for item in daemon.webhook.poll_burst]
    assert burst == [
        (NOW + timedelta(seconds=offset)).isoformat() for offset in (30, 60, 120, 240)
    ]
    text = log.getvalue() + (tmp_path / "state" / "bridge.log").read_text(encoding="utf-8")
    assert WEBHOOK_URL not in text
    assert WEBHOOK_KEY not in text
    assert "Authorization" not in text


def test_coalesce_and_pace_send_one_post(tmp_path: Path):
    script = Script([200, 200])
    daemon, clock, _seen, _log = _boot(tmp_path, script)
    _enqueue(daemon, "a-coal1", NOW)
    _enqueue(daemon, "a-coal2", NOW)
    daemon.tick_webhook()
    assert script.calls == []
    clock.moment = NOW + timedelta(seconds=20)
    daemon.tick_webhook()
    assert len(script.calls) == 1
    assert len(script.calls[0][2]["actions"]) == 2
    assert "title" not in script.calls[0][2]["actions"][0]
    assert "kind" not in script.calls[0][2]["actions"][0]
    _enqueue(daemon, "a-pace1", clock.moment)
    clock.moment = NOW + timedelta(seconds=40)
    daemon.tick_webhook()
    assert len(script.calls) == 1
    clock.moment = NOW + timedelta(seconds=80)
    daemon.tick_webhook()
    assert len(script.calls) == 2


def test_daily_cap_holds_the_second_post_until_the_next_utc_day(tmp_path: Path):
    script = Script([200, 200])
    daemon, clock, _seen, _log = _boot(tmp_path, script, daily_cap=1)
    _enqueue(daemon, "a-day1", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    _enqueue(daemon, "a-day2", NOW)
    clock.moment = NOW + timedelta(minutes=2)
    daemon.tick_webhook()
    assert len(script.calls) == 1
    clock.moment = NOW + timedelta(days=1)
    daemon.tick_webhook()
    assert len(script.calls) == 2


def test_rate_cap_parks_on_the_eighth_try(tmp_path: Path):
    script = Script([400] * 8)
    daemon, clock, seen, _log = _boot(tmp_path, script)
    _enqueue(daemon, "a-rate1", NOW - timedelta(seconds=30))
    moment = NOW
    for attempt in range(1, 9):
        clock.moment = moment
        daemon.tick_webhook()
        assert len(script.calls) == attempt
        row = daemon.queue.snapshot()[0]
        if attempt < 8:
            assert row.state == "pending"
            assert row.attempts == attempt
            assert row.detail.startswith("retry-after:")
            moment = _moment(row.detail)
            assert ("ActionResult", ("a-rate1", "queued_retry", row.detail)) in seen
        else:
            assert row.state == "parked"
            assert row.detail == "rate cap"
    notices = [item for item in seen if item[0] == "NotificationRequested"]
    assert notices
    assert notices[-1][1][1] == "delivery_failed"
    assert WEBHOOK_URL not in notices[-1][1][0]
    clock.moment = moment + timedelta(hours=2)
    daemon.tick_webhook()
    assert len(script.calls) == 8


def test_rejected_key_stops_the_route_until_retry(tmp_path: Path):
    script = Script([401, 200])
    daemon, clock, seen, log = _boot(tmp_path, script)
    _enqueue(daemon, "a-key1", NOW - timedelta(seconds=30))
    _enqueue(daemon, "a-key2", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    rows = daemon.queue.snapshot()
    assert [row.state for row in rows] == ["parked", "parked"]
    assert {row.detail for row in rows} == {"re-paste key"}
    assert daemon.state == "degraded"
    assert daemon.reason == "re-paste key"
    assert daemon.webhook.status().state == "rejected-key"
    posted = log.getvalue() + (tmp_path / "state" / "bridge.log").read_text(encoding="utf-8")
    assert "result=rejected_key" in posted
    assert "status=401" in posted
    assert WEBHOOK_URL not in posted
    assert WEBHOOK_KEY not in posted
    assert ("PropertiesChanged", (("QueueLength", "Counts"),)) in seen
    assert daemon.api.properties()["QueueLength"] == 0
    notice = next(item for item in seen if item[0] == "NotificationRequested")
    payload = json.loads(notice[1][0])
    assert notice[1][1] == "re-paste"
    assert payload["title"] == "Re-paste key"
    assert payload["slot"] == "primary-actions"
    assert "request_secret" in payload["actions"]
    assert WEBHOOK_URL not in notice[1][0]
    assert WEBHOOK_KEY not in notice[1][0]
    routes = tmp_path / "state" / "webhook-routes.json"
    assert routes.stat().st_mode & 0o777 == 0o600
    assert WEBHOOK_KEY not in routes.read_text(encoding="utf-8")
    daemon.tick_webhook()
    assert len(script.calls) == 1
    daemon.api.call("RetryParked", ("a-key1",))
    daemon.api.call("RetryParked", ("a-key2",))
    clock.moment = NOW + timedelta(seconds=60)
    daemon.tick_webhook()
    assert len(script.calls) == 2
    assert [row["action_id"] for row in script.calls[1][2]["actions"]] == ["a-key1", "a-key2"]
    assert daemon.queue.snapshot() == ()
    assert daemon.state == "ok"
    stored = json.loads(routes.read_text(encoding="utf-8"))
    assert stored["stopped"] == {}


def test_missing_routine_uses_its_own_text(tmp_path: Path):
    script = Script([404])
    daemon, _clock, seen, _log = _boot(tmp_path, script)
    _enqueue(daemon, "a-gone1", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    row = daemon.queue.snapshot()[0]
    assert row.state == "parked"
    assert row.detail == "Routine not found"
    assert daemon.reason == "Routine not found"
    assert ("ActionResult", ("a-gone1", "rejected_key", "Routine not found")) in seen


def test_timeout_retries_once_with_the_same_action_id(tmp_path: Path):
    script = Script([HttpOutcome("timeout"), 200])
    daemon, clock, _seen, _log = _boot(tmp_path, script)
    _enqueue(daemon, "a-time1", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    row = daemon.queue.snapshot()[0]
    assert row.detail.startswith("timeout-retry-after:")
    clock.moment = _moment(row.detail)
    daemon.tick_webhook()
    assert [call[2]["actions"][0]["action_id"] for call in script.calls] == ["a-time1", "a-time1"]
    assert daemon.queue.snapshot() == ()


def test_second_timeout_parks(tmp_path: Path):
    script = Script([HttpOutcome("timeout"), HttpOutcome("timeout")])
    daemon, clock, seen, _log = _boot(tmp_path, script)
    _enqueue(daemon, "a-time2", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    clock.moment = _moment(daemon.queue.snapshot()[0].detail)
    daemon.tick_webhook()
    row = daemon.queue.snapshot()[0]
    assert row.state == "parked"
    assert row.detail == "timeout"
    assert ("ActionResult", ("a-time2", "parked", "timeout")) in seen
    daemon.tick_webhook()
    assert len(script.calls) == 2


def test_offline_does_not_post_or_count_a_try(tmp_path: Path):
    script = Script([200])
    online = {"value": False}
    daemon, _clock, _seen, _log = _boot(tmp_path, script, online=lambda: online["value"])
    _enqueue(daemon, "a-off1", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    assert script.calls == []
    assert daemon.state == "offline"
    assert daemon.queue.snapshot()[0].attempts == 0
    online["value"] = True
    daemon.tick_webhook()
    assert len(script.calls) == 1
    assert daemon.state == "ok"


def test_missing_secret_waits_without_posting(tmp_path: Path):
    script = Script([200])
    daemon, _clock, seen, log = _boot(tmp_path, script, store_secret=False)
    _enqueue(daemon, "a-miss1", NOW - timedelta(seconds=30))
    daemon.tick_webhook()
    daemon.tick_webhook()
    assert script.calls == []
    assert daemon.queue.snapshot()[0].state == "pending"
    assert daemon.reason == "webhook secret is not stored"
    notices = [item for item in seen if item[0] == "NotificationRequested"]
    assert len(notices) == 1
    assert WEBHOOK_URL not in log.getvalue()


def test_other_bot_is_not_parked_for_a_rejected_key(tmp_path: Path):
    script = Script([403, 200])
    daemon, _clock, _seen, _log = _boot(tmp_path, script, extra_bot=True)
    daemon.secrets.put_webhook("zeta-actions", "https://example.test/hook/zeta", "zeta-hook-key")
    _enqueue(daemon, "a-pri1", NOW - timedelta(seconds=30))
    _enqueue(daemon, "a-zeta1", NOW - timedelta(seconds=30), bot="zeta")
    daemon.tick_webhook()
    daemon.tick_webhook()
    parked = {row.action_id: row.state for row in daemon.queue.snapshot()}
    assert parked == {"a-pri1": "parked"}
    assert [call[0] for call in script.calls] == [
        WEBHOOK_URL,
        "https://example.test/hook/zeta",
    ]
    assert script.calls[0][1] == WEBHOOK_KEY
    assert "zeta-hook-key" not in json.dumps(script.calls[0][2])


def test_post_json_rejects_http_and_does_not_follow_redirects():
    def explode(*_args, **_kwargs):
        raise AssertionError("opened a socket")

    refused = post_json("http://example.test/hook", WEBHOOK_KEY, b"{}", opener=_Opener(explode))
    assert refused.kind == "refused"

    def redirected(request, timeout):
        assert timeout == 30
        assert request.get_header("Authorization") == f"Bearer {WEBHOOK_KEY}"
        assert request.get_header("Content-type") == "application/json"
        raise urllib.error.HTTPError(WEBHOOK_URL, 302, "found", None, None)

    outcome = post_json(WEBHOOK_URL, WEBHOOK_KEY, b"{}", opener=_Opener(redirected))
    assert outcome.status == 302
    assert _NoRedirect().redirect_request(None, None, 302, "found", {}, "https://evil.test") is None


def test_plan_table_matches_the_spec():
    accepted = plan_for(HttpOutcome("status", 200), timeout_retry=False, attempts=1)
    assert accepted.result == "accepted"
    refused = plan_for(HttpOutcome("status", 401), timeout_retry=False, attempts=1)
    assert refused.stop == "re-paste key"
    missing = plan_for(HttpOutcome("status", 410), timeout_retry=False, attempts=1)
    assert missing.detail == "Routine not found"
    retry = plan_for(HttpOutcome("status", 429), timeout_retry=False, attempts=7)
    assert retry.hold_prefix == "retry-after:"
    parked = plan_for(HttpOutcome("status", 500), timeout_retry=False, attempts=8)
    assert parked.detail == "rate cap"
    again = plan_for(HttpOutcome("timeout"), timeout_retry=False, attempts=1)
    assert again.hold_prefix == "timeout-retry-after:"
    done = plan_for(HttpOutcome("timeout"), timeout_retry=True, attempts=2)
    assert done.detail == "timeout"
    assert PROFILE == "routine-webhook-2026-10"


def test_locked_keyring_holds_the_action_until_unlock(tmp_path: Path):
    backend = MemoryBackend()
    script = Script([200])
    clock = Clock()
    log = StringIO()
    (tmp_path / "config.toml").write_text(_CONFIG, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=log,
        clock=clock,
        secrets=SecretStore(backend),
        webhook_post=script,
        webhook_jitter=lambda _delay: 0,
    )
    daemon.start()
    daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    _enqueue(daemon, "a-lock1", NOW - timedelta(seconds=30))
    backend._status = "locked"
    daemon.tick_adapters()
    assert daemon.state == "degraded"
    assert daemon.reason == "keyring locked"
    assert script.calls == []
    row = daemon.queue.snapshot()[0]
    assert row.state == "pending"
    assert row.attempts == 0
    assert "bridge degraded: keyring locked" in log.getvalue()
    assert WEBHOOK_URL not in log.getvalue()
    assert WEBHOOK_KEY not in log.getvalue()
    backend._status = "available"
    daemon.tick_adapters()
    assert len(script.calls) == 1
    assert daemon.queue.snapshot() == ()
    assert daemon.state == "ok"
    assert daemon.reason == ""


def test_import_does_not_load_gi():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import sys, tetherbot.adapters.webhook_sender\n"
        "bad = [name for name in sys.modules if name == 'gi' or name.startswith('gi.')]\n"
        "raise SystemExit(0 if not bad else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env, timeout=20)


def _boot(
    tmp_path: Path,
    script: Script,
    *,
    online=None,
    daily_cap: int | None = None,
    store_secret: bool = True,
    extra_bot: bool = False,
):
    clock = Clock()
    log = StringIO()
    text = _CONFIG
    if extra_bot:
        text += '[bots.zeta]\nwebhook_slot = "zeta-actions"\n'
    if daily_cap is not None:
        text += f"\n[queue]\ndaily_cap = {daily_cap}\n"
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=log,
        clock=clock,
        secrets=SecretStore(MemoryBackend()),
        webhook_post=script,
        webhook_online=online,
        webhook_jitter=lambda _delay: 0,
    )
    daemon.start()
    assert daemon.api is not None
    seen: list[tuple[str, tuple[object, ...]]] = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    if store_secret:
        daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    return daemon, clock, seen, log


def _enqueue(daemon: BridgeDaemon, action_id: str, created, bot: str = "primary") -> None:
    assert daemon.queue is not None
    daemon.queue.enqueue(
        bot=bot,
        item=f"{bot}/sample-01",
        action="approve",
        created=created.isoformat(),
        action_id=action_id,
    )


def _moment(detail: str):
    prefix = "timeout-retry-after:" if detail.startswith("timeout") else "retry-after:"
    return parse_iso8601(detail[len(prefix) :], field_name="retry-after")


class _Opener:
    def __init__(self, open_request) -> None:
        self._open_request = open_request

    def open(self, request, timeout=None):
        return self._open_request(request, timeout)

# SPDX-License-Identifier: GPL-2.0-or-later
"""Clipboard send posts one text entry and does not keep a copy of it."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import NOW
from tests.test_clipboard import LOOKALIKE, tiny_png
from tetherbot.adapters.webhook_sender import HttpOutcome, clip_envelope
from tetherbot.config import BotConfig
from tetherbot.daemon import BridgeDaemon
from tetherbot.model import ENVELOPE_ACTIONS
from tetherbot.secrets import MemoryBackend, SecretStore
from tetherbot.service import ServiceError
from tetherbot.ui_settings import UiSettings

WEBHOOK_URL = "https://example.test/hook/primary"
WEBHOOK_KEY = "desk-hook-key"
SAMPLE = "sample clipboard line for the bot"
META = json.dumps({"mimes": ["text/plain"], "wm_class": "gedit"})
_CONFIG = """\
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[adapters.webhook-sender]
enabled = true

[bots.primary]
webhook_slot = "primary-actions"
"""
_OFF = """\
schema = "tetherbot/1"

[bridge]
mode = "webhook-only"

[bots.primary]
webhook_slot = "primary-actions"
"""
COPIED_AT = datetime.fromtimestamp(1_700_000_000, UTC).isoformat()


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


def test_clip_envelope_omits_an_unknown_app_and_keeps_names_only():
    bare = json.loads(
        clip_envelope(
            action="clip-ask",
            action_id="a-clip0001",
            created="2026-10-17T12:00:00+00:00",
            sent_at=NOW,
            entry_id="c-abc12345",
            text=SAMPLE,
            tags=["Later"],
            copied_at=COPIED_AT,
        )
    )
    row = bare["actions"][0]
    assert bare["schema"] == "tetherbot/1"
    assert bare["type"] == "actions"
    assert row["action"] == "clip-ask"
    assert row["item"] == "clipboard/c-abc12345"
    assert row["args"] == {}
    assert set(row["clip"]) == {"text", "tags", "copied_at", "effort", "target_bot"}
    assert row["clip"]["effort"] == "low"
    assert row["clip"]["target_bot"] == "primary"
    assert row["clip"]["tags"] == ["Later"]
    named = json.loads(
        clip_envelope(
            action="clip-todo",
            action_id="a-clip0002",
            created="2026-10-17T12:00:00+00:00",
            sent_at=NOW,
            entry_id="c-abc12345",
            text=SAMPLE,
            tags=[],
            copied_at=COPIED_AT,
            source_app="gedit",
        )
    )
    assert named["actions"][0]["clip"]["source_app"] == "gedit"
    assert "clip-todo" not in ENVELOPE_ACTIONS


def test_a_text_entry_is_posted_once_and_not_stored_again(tmp_path: Path):
    script = Script([200])
    daemon, clock, seen, log = _boot(tmp_path, script)
    ident = _offer(daemon, SAMPLE)
    listed = json.loads(daemon.api.call("GetClipboard", ("",))[0])
    assert "source_app" not in listed[0]
    assert daemon.api.call(
        "SetClipboardTags",
        (ident, '[{"name":"Later","color":"blue"}]'),
    ) == (True,)
    seen.clear()

    def refuse_queue(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("clipboard send queued the text")

    assert daemon.queue is not None
    daemon.queue.enqueue = refuse_queue  # type: ignore[method-assign]
    assert daemon.api.call("SendClipboard", (ident, "clip-todo")) == ("sent",)
    assert len(script.calls) == 1
    url, key, body = script.calls[0]
    assert url == WEBHOOK_URL
    assert key == WEBHOOK_KEY
    assert body["schema"] == "tetherbot/1"
    assert body["type"] == "actions"
    assert body["client"]["name"] == "tetherbot"
    assert body["client"]["host"] == "desktop"
    row = body["actions"][0]
    assert row["action"] == "clip-todo"
    assert row["item"] == f"clipboard/{ident}"
    assert row["args"] == {}
    clip = row["clip"]
    assert set(clip) <= {"text", "tags", "source_app", "copied_at", "effort", "target_bot"}
    assert clip["effort"] == "low"
    assert clip["target_bot"] == "primary"
    assert clip["text"] == SAMPLE
    assert clip["tags"] == ["Later"]
    assert clip["source_app"] == "gedit"
    assert clip["copied_at"] == COPIED_AT
    encoded = json.dumps(body)
    assert "blue" not in encoded
    assert "path" not in clip
    assert "sha256" not in encoded
    assert "thumb" not in encoded
    assert WEBHOOK_KEY not in encoded
    assert WEBHOOK_URL not in encoded
    assert not any(name == "ClipboardChanged" for name, _args in seen)
    clock.moment = NOW + timedelta(seconds=4)
    with pytest.raises(ServiceError, match="Wait a few seconds"):
        daemon.api.call("SendClipboard", (ident, "clip-ask"))
    assert len(script.calls) == 1
    clock.moment = NOW + timedelta(seconds=5)
    script.outcomes.append(200)
    assert daemon.api.call("SendClipboard", (ident, "clip-todo-context")) == ("sent",)
    assert script.calls[1][2]["actions"][0]["action"] == "clip-todo-context"
    logged = _logged(tmp_path, log)
    assert f"clipboard send action=clip-todo entry={ident} result=sent" in logged
    assert SAMPLE not in logged
    _assert_text_stays_in_history(tmp_path, SAMPLE)
    routes = tmp_path / "state" / "webhook-routes.json"
    assert not routes.exists()


def test_effort_comes_from_settings_and_the_post_stays_on_primary(tmp_path: Path):
    script = Script([200, 200, 200])
    daemon, clock, _seen, log = _boot(tmp_path, script)
    assert daemon.config is not None
    daemon.config.bots["notes"] = BotConfig(webhook_slot="")
    daemon.ui_settings = UiSettings(context_effort="high")
    ident = _offer(daemon, SAMPLE)
    assert daemon.api is not None
    assert daemon.api.call("SendClipboard", (ident, "clip-todo", "notes")) == ("sent",)
    url, _key, body = script.calls[0]
    clip = body["actions"][0]["clip"]
    assert url == WEBHOOK_URL
    assert clip["effort"] == "high"
    assert clip["target_bot"] == "notes"
    assert clip["text"] == SAMPLE
    leaked = "notes\nnot-a-bot"
    clock.moment = NOW + timedelta(seconds=5)
    assert daemon.api.call("SendClipboard", (ident, "clip-ask", leaked)) == ("sent",)
    second = script.calls[1][2]["actions"][0]["clip"]
    assert second["target_bot"] == "primary"
    assert second["effort"] == "high"
    assert script.calls[1][0] == WEBHOOK_URL
    assert leaked not in _logged(tmp_path, log)
    assert SAMPLE not in _logged(tmp_path, log)
    daemon.ui_settings = UiSettings(context_effort="nope")
    clock.moment = NOW + timedelta(seconds=10)
    assert daemon.api.call("SendClipboard", (ident, "clip-todo-context", "")) == ("sent",)
    third = script.calls[2][2]["actions"][0]["clip"]
    assert third["effort"] == "low"
    assert third["target_bot"] == "primary"
    assert script.calls[2][2]["actions"][0]["action"] == "clip-todo-context"


def test_a_missing_secret_is_not_queued(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, log = _boot(tmp_path, script, store_secret=False)
    ident = _offer(daemon, SAMPLE)
    with pytest.raises(ServiceError, match="No webhook set up"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    assert daemon.queue is not None
    assert daemon.queue.snapshot() == ()
    daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    assert daemon.api.call("SendClipboard", (ident, "clip-todo")) == ("sent",)
    assert len(script.calls) == 1
    assert SAMPLE not in _logged(tmp_path, log)


def test_a_disabled_sender_does_not_post(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, log = _boot(tmp_path, script, enabled=False)
    daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    ident = _offer(daemon, SAMPLE)
    with pytest.raises(ServiceError, match="Webhook sender is off"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    assert daemon.queue is not None
    assert daemon.queue.snapshot() == ()
    assert SAMPLE not in _logged(tmp_path, log)


def test_a_locked_keyring_and_a_bad_secret_fail_closed(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, _log = _boot(tmp_path, script)
    ident = _offer(daemon, SAMPLE)
    daemon.secrets._backend._status = "locked"  # type: ignore[attr-defined]
    with pytest.raises(ServiceError, match="Keyring is locked"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    daemon.secrets._backend._status = "available"  # type: ignore[attr-defined]
    daemon.secrets._backend.store(  # type: ignore[attr-defined]
        "webhook",
        "primary-actions",
        "tetherbot",
        "not-json",
    )
    with pytest.raises(ServiceError, match="Webhook secret is unreadable"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    assert daemon.queue is not None
    assert daemon.queue.snapshot() == ()


def test_text_over_8000_characters_is_refused(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, log = _boot(tmp_path, script)
    long = "é" * 8001
    assert len(long) == 8001
    assert len(long.encode("utf-8")) > 8001
    ident = _offer(daemon, long)
    with pytest.raises(ServiceError, match="Clipboard text is longer than 8000 characters"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    assert long not in _logged(tmp_path, log)
    _assert_text_stays_in_history(tmp_path, long)
    short = "é" * 8000
    other = _offer(daemon, short)
    assert daemon.api.call("SendClipboard", (other, "clip-ask")) == ("sent",)
    assert script.calls[0][2]["actions"][0]["clip"]["text"] == short


def test_an_image_and_a_hidden_password_are_not_sent(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, log = _boot(tmp_path, script)
    blob = tiny_png(note=b"marker-not-logged")
    meta = json.dumps({"mimes": ["image/png"], "wm_class": "gedit", "mime": "image/png"})
    assert daemon.api.call("OfferClipboardImage", (blob, meta)) == ("stored",)
    image = json.loads(daemon.api.call("GetClipboard", ("",))[0])[0]["id"]
    with pytest.raises(ServiceError, match="Images are not sent"):
        daemon.api.call("SendClipboard", (image, "clip-todo"))
    daemon.ui_settings = UiSettings(clipboard_lookalike="mask")
    assert daemon.api.call("OfferClipboard", (LOOKALIKE, META)) == ("stored-masked",)
    hidden = next(
        row["id"]
        for row in json.loads(daemon.api.call("GetClipboard", ("",))[0])
        if row.get("masked") is True
    )
    with pytest.raises(ServiceError, match="Hidden passwords are not sent"):
        daemon.api.call("SendClipboard", (hidden, "clip-todo-context"))
    assert script.calls == []
    logged = _logged(tmp_path, log)
    assert LOOKALIKE not in logged
    assert "marker-not-logged" not in logged
    assert daemon.queue is not None
    assert daemon.queue.snapshot() == ()
    _assert_text_stays_in_history(tmp_path, LOOKALIKE)


def test_http_failures_are_visible_and_do_not_queue(tmp_path: Path):
    script = Script([500])
    daemon, _clock, _seen, _log = _boot(tmp_path, script)
    ident = _offer(daemon, SAMPLE)
    with pytest.raises(ServiceError, match="Webhook did not accept the send"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    with pytest.raises(ServiceError, match="Wait a few seconds"):
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert len(script.calls) == 1
    assert daemon.queue is not None
    assert daemon.queue.snapshot() == ()
    assert not (tmp_path / "state" / "webhook-routes.json").exists()


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (401, "re-paste key"),
        (403, "re-paste key"),
        (404, "Routine not found"),
        (410, "Routine not found"),
        (HttpOutcome("timeout"), "Could not reach the webhook"),
        (HttpOutcome("network"), "Could not reach the webhook"),
        (HttpOutcome("tls"), "Could not reach the webhook"),
    ],
)
def test_webhook_errors_name_the_reason(tmp_path: Path, outcome: object, reason: str):
    script = Script([outcome])
    daemon, _clock, _seen, log = _boot(tmp_path, script)
    ident = _offer(daemon, SAMPLE)
    with pytest.raises(ServiceError, match=reason):
        daemon.api.call("SendClipboard", (ident, "clip-ask"))
    assert len(script.calls) == 1
    assert not (tmp_path / "state" / "webhook-routes.json").exists()
    assert SAMPLE not in _logged(tmp_path, log)
    assert WEBHOOK_URL not in _logged(tmp_path, log)
    assert WEBHOOK_KEY not in _logged(tmp_path, log)


def test_a_bad_action_is_logged_without_its_text(tmp_path: Path):
    script = Script([200])
    daemon, _clock, _seen, log = _boot(tmp_path, script)
    ident = _offer(daemon, SAMPLE)
    leaked = "pasted-secret-line"
    with pytest.raises(ServiceError, match="action is not a clipboard send"):
        daemon.api.call("SendClipboard", (ident, leaked))
    with pytest.raises(ServiceError, match="Clipboard entry is not available"):
        daemon.api.call("SendClipboard", ("c-00000000", "clip-todo"))
    with pytest.raises(ServiceError, match="Nothing to send"):
        assert daemon.clipboard is not None
        daemon.clipboard.entries[0]["text"] = ""
        daemon.api.call("SendClipboard", (ident, "clip-todo"))
    assert script.calls == []
    logged = _logged(tmp_path, log)
    assert "action=invalid" in logged
    assert leaked not in logged
    assert SAMPLE not in logged
    assert "entry=c-00000000" in logged


def _boot(
    tmp_path: Path,
    script: Script,
    *,
    store_secret: bool = True,
    enabled: bool = True,
):
    (tmp_path / "repos").mkdir()
    (tmp_path / "desktop").mkdir()
    clock = Clock()
    log = StringIO()
    (tmp_path / "config.toml").write_text(_CONFIG if enabled else _OFF, encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        repos_dir=tmp_path / "repos",
        log_stream=log,
        clock=clock,
        secrets=SecretStore(MemoryBackend()),
        webhook_post=script,
        webhook_jitter=lambda _delay: 0,
    )
    daemon.start()
    assert daemon.api is not None
    assert daemon.clipboard is not None
    daemon.clipboard._clock = lambda: 1_700_000_000
    seen: list[tuple[str, tuple[object, ...]]] = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    if store_secret:
        daemon.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    return daemon, clock, seen, log


def _offer(daemon: BridgeDaemon, text: str) -> str:
    assert daemon.api is not None
    assert daemon.api.call("OfferClipboard", (text, META)) == ("stored",)
    rows = json.loads(daemon.api.call("GetClipboard", ("",))[0])
    found = next(row for row in rows if row.get("text") == text)
    return str(found["id"])


def _logged(tmp_path: Path, log: StringIO) -> str:
    path = tmp_path / "state" / "bridge.log"
    disk = path.read_text(encoding="utf-8") if path.is_file() else ""
    return log.getvalue() + disk


def _assert_text_stays_in_history(tmp_path: Path, text: str) -> None:
    """The copied line may live in clipboard.json and nowhere else."""

    needle = text.encode("utf-8")
    hits = [
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "clipboard.json" and needle in path.read_bytes()
    ]
    assert hits == []

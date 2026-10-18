# SPDX-License-Identifier: GPL-2.0-or-later
"""Daemon lifecycle without PyGObject, D-Bus, or the network."""

import os
import stat
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import NOW, make_item
from tetherbot.daemon import (
    BridgeDaemon,
    default_config_path,
    default_repos_dir,
    default_state_dir,
)
from tetherbot.queue import ActionQueue
from tetherbot.secrets import MemoryBackend, SecretStore, UnavailableBackend
from tetherbot.store import ItemStore

ROOT = Path(__file__).resolve().parents[1]


class ScriptedLoop:
    def __init__(self) -> None:
        self.quit_count = 0
        self.callbacks: list = []

    def run(self) -> None:
        for callback in list(self.callbacks):
            callback()

    def quit(self) -> None:
        self.quit_count += 1

    def watch_unix_signals(self, callback) -> None:
        self.callbacks.append(callback)


def _daemon(tmp_path: Path, **kwargs: object) -> BridgeDaemon:
    loop = kwargs.pop("loop", None)
    clock = kwargs.pop("clock", lambda: NOW)
    secrets = kwargs.pop("secrets", None)
    return BridgeDaemon(
        config_path=kwargs.pop("config_path", tmp_path / "config.toml"),  # type: ignore[arg-type]
        state_dir=kwargs.pop("state_dir", tmp_path / "state"),  # type: ignore[arg-type]
        loop=loop,  # type: ignore[arg-type]
        log_stream=StringIO(),
        clock=clock,  # type: ignore[arg-type]
        secrets=secrets,  # type: ignore[arg-type]
        repos_dir=kwargs.pop("repos_dir", tmp_path / "repos"),  # type: ignore[arg-type]
    )


def _write_config(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_missing_config_is_unconfigured_and_private(tmp_path: Path):
    daemon = _daemon(tmp_path)
    status = daemon.start()
    assert status.state == "unconfigured"
    assert status.reason == "config.toml is missing"
    assert status.running is True
    assert status.mode is None
    assert status.queue_length == 0
    assert not daemon.config_path.exists()
    assert stat.S_IMODE(daemon.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((daemon.state_dir / "queue").stat().st_mode) == 0o700
    log = daemon.state_dir / "bridge.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert "unconfigured: config.toml is missing" in log.read_text(encoding="utf-8")
    daemon.stop()
    assert daemon.running is False
    assert "bridge stopping" in log.read_text(encoding="utf-8")
    daemon.stop()


def test_disabled_example_shape_stays_unconfigured(tmp_path: Path):
    _write_config(
        tmp_path / "config.toml",
        'schema = "tetherbot/1"\n[bridge]\nmode = "webhook-only"\n'
        "[adapters.webhook-sender]\nenabled = false\n",
    )
    daemon = _daemon(tmp_path)
    status = daemon.start()
    assert status.state == "unconfigured"
    assert status.reason == "no adapter is enabled"
    assert status.mode == "webhook-only"
    assert daemon.queue is not None
    assert daemon.queue.coalesce_seconds == 20


def test_refused_config_fails_closed_without_logging_the_secret(tmp_path: Path):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz"
    _write_config(
        tmp_path / "config.toml",
        f'schema = "tetherbot/1"\nnote = "{secret}"\n',
    )
    daemon = _daemon(tmp_path)
    status = daemon.start()
    assert status.state == "failed_closed"
    assert "looks like a secret" in status.reason
    assert secret not in status.reason
    text = (daemon.state_dir / "bridge.log").read_text(encoding="utf-8")
    assert secret not in text
    assert "ghp_" not in text


def test_unknown_schema_fails_closed(tmp_path: Path):
    _write_config(tmp_path / "config.toml", 'schema = "tetherbot/2"\n')
    status = _daemon(tmp_path).start()
    assert status.state == "failed_closed"
    assert "unsupported schema tetherbot/2" in status.reason


def test_enabled_adapter_is_not_started(tmp_path: Path):
    _write_config(
        tmp_path / "config.toml",
        'schema = "tetherbot/1"\n[bridge]\nmode = "full"\n'
        "[adapters.webhook-sender]\nenabled = true\n"
        "[sinks.legacy-todo]\nenabled = true\n",
    )
    daemon = _daemon(tmp_path)
    status = daemon.start()
    assert status.state == "degraded"
    assert status.reason == "not started: legacy-todo"
    assert daemon.webhook is not None
    assert daemon.webhook.status().state == "running"


def test_queue_limits_and_resume(tmp_path: Path):
    state = tmp_path / "state"
    queue = ActionQueue(state / "queue", coalesce_seconds=15, coalesce_max_seconds=40)
    queue.enqueue(
        bot="primary",
        item="primary/sample-01",
        action="approve",
        created=NOW.isoformat(),
        action_id="a-resume1",
    )
    _write_config(
        tmp_path / "config.toml",
        'schema = "tetherbot/1"\n[bridge]\nmode = "repo-only"\n'
        "[queue]\ncoalesce_seconds = 15\ncoalesce_max_seconds = 40\n"
        "min_interval_seconds = 60\ndaily_cap = 30\n",
    )
    daemon = _daemon(tmp_path, state_dir=state)
    status = daemon.start()
    assert status.queue_length == 1
    assert daemon.queue is not None
    assert daemon.queue.coalesce_seconds == 15
    assert (state / "queue" / "a-resume1.json").is_file()


def test_startup_refreshes_expiry(tmp_path: Path):
    state = tmp_path / "state"
    store = ItemStore(state / "items.json")
    store.replace_origin(
        "feed",
        [make_item(expires_at="2026-10-17T11:00:00+00:00", due=None)],
        now=NOW - timedelta(hours=2),
    )
    assert store.get("primary/sample-01").status == "open"
    daemon = _daemon(tmp_path, state_dir=state)
    daemon.start()
    assert daemon.store is not None
    assert daemon.store.get("primary/sample-01").status == "expired"


def test_corrupt_cache_stays_on_disk(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    cache = state / "items.json"
    cache.write_text("{", encoding="utf-8")
    daemon = _daemon(tmp_path, state_dir=state)
    status = daemon.start()
    assert status.state == "degraded"
    assert "items cache" in status.reason
    assert cache.read_text(encoding="utf-8") == "{"


def test_unreadable_queue_file_is_left_in_place(tmp_path: Path):
    state = tmp_path / "state"
    queue_dir = state / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "a-bad.json").write_text("{", encoding="utf-8")
    status = _daemon(tmp_path, state_dir=state).start()
    assert status.state == "degraded"
    assert status.reason == "action queue has unreadable files"
    assert (queue_dir / "a-bad.json").read_text(encoding="utf-8") == "{"


def test_run_returns_when_the_loop_returns(tmp_path: Path):
    loop = ScriptedLoop()
    daemon = _daemon(tmp_path, loop=loop)
    assert daemon.run() == 0
    assert loop.quit_count == 1
    assert daemon.running is False


def test_signal_callback_stops_once(tmp_path: Path):
    loop = ScriptedLoop()
    daemon = _daemon(tmp_path, loop=loop)
    assert daemon.run(install_signals=True) == 0
    assert loop.quit_count == 1
    assert daemon.running is False


def test_start_twice_is_refused(tmp_path: Path):
    daemon = _daemon(tmp_path)
    daemon.start()
    with pytest.raises(RuntimeError, match="already started"):
        daemon.start()


def test_default_paths_follow_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert default_config_path() == tmp_path / "config" / "tetherbot" / "config.toml"
    assert default_state_dir() == tmp_path / "state" / "tetherbot"
    assert default_repos_dir() == tmp_path / "data" / "tetherbot" / "repos"
    monkeypatch.setenv("XDG_CONFIG_HOME", "  ")
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_config_path() == tmp_path / ".config" / "tetherbot" / "config.toml"
    assert default_state_dir() == tmp_path / ".local" / "state" / "tetherbot"
    assert default_repos_dir() == tmp_path / ".local" / "share" / "tetherbot" / "repos"


def test_locked_keyring_is_reported_and_then_cleared(tmp_path: Path):
    backend = MemoryBackend()
    _write_config(
        tmp_path / "config.toml",
        'schema = "tetherbot/1"\n[bridge]\nmode = "webhook-only"\n'
        "[adapters.webhook-sender]\nenabled = true\n",
    )
    daemon = _daemon(tmp_path, secrets=SecretStore(backend))
    daemon.start()
    assert daemon.state == "ok"
    backend._status = "locked"
    daemon.tick_adapters()
    assert daemon.state == "degraded"
    assert daemon.reason == "keyring locked"
    backend._status = "available"
    daemon.tick_adapters()
    assert daemon.state == "ok"
    assert daemon.reason == ""


def test_unconfigured_stays_unconfigured_when_the_keyring_is_locked(tmp_path: Path):
    backend = MemoryBackend(status="locked")
    daemon = _daemon(tmp_path, secrets=SecretStore(backend))
    daemon.start()
    daemon._apply_keyring_state()
    daemon.tick_adapters()
    assert daemon.state == "unconfigured"
    assert daemon.reason == "config.toml is missing"


def test_missing_secret_service_holds_an_enabled_adapter(tmp_path: Path):
    _write_config(
        tmp_path / "config.toml",
        'schema = "tetherbot/1"\n[bridge]\nmode = "webhook-only"\n'
        "[adapters.webhook-sender]\nenabled = true\n",
    )
    daemon = _daemon(tmp_path, secrets=SecretStore(UnavailableBackend()))
    daemon.start()
    assert daemon.state == "ok"
    daemon._apply_keyring_state()
    assert daemon.state == "degraded"
    assert daemon.reason == "keyring locked"


def test_failed_closed_overlay_wins_while_the_base_state_is_ok(tmp_path: Path):
    daemon = _daemon(tmp_path)
    daemon.start()
    daemon.base_state = "ok"
    daemon.base_reason = ""
    daemon.webhook = type("Sender", (), {"overlay": ("degraded", "re-paste key")})()
    daemon.poller = type("Poller", (), {"overlay": ("failed_closed", "rebase conflict")})()
    daemon._apply_overlay()
    assert daemon.state == "failed_closed"
    assert daemon.reason == "rebase conflict"
    daemon.base_state = "degraded"
    daemon.base_reason = "keyring locked"
    daemon._apply_overlay()
    assert daemon.state == "degraded"
    assert daemon.reason == "keyring locked"


def test_import_does_not_load_glib_or_adapters():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import sys, tetherbot.daemon\n"
        "bad = [name for name in sys.modules if name.startswith('gi') "
        "or name.startswith('tetherbot.adapters') or name.startswith('tetherbot.sinks')]\n"
        "raise SystemExit(0 if not bad else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_main_rejects_arguments_and_missing_glib(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from tetherbot.__main__ import main

    assert main(["--debug"]) == 2
    assert "no arguments" in capsys.readouterr().err

    class Broken:
        def run(self, *, install_signals: bool = False) -> int:
            del install_signals
            raise ImportError("no gi")

    monkeypatch.setattr("tetherbot.__main__.BridgeDaemon", Broken)
    assert main([]) == 1
    assert "python3-gobject" in capsys.readouterr().err

    class Denied:
        def run(self, *, install_signals: bool = False) -> int:
            del install_signals
            raise OSError(13, "Permission denied")

    monkeypatch.setattr("tetherbot.__main__.BridgeDaemon", Denied)
    assert main([]) == 1
    assert "Permission denied" in capsys.readouterr().err

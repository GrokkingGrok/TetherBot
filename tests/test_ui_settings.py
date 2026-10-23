# SPDX-License-Identifier: GPL-2.0-or-later
"""UI setting bounds. Secrets are not part of this snapshot."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tetherbot.adapters.github_poller import GitHubPoller
from tetherbot.secret_dialog import launch_secret_dialog, save_slot
from tetherbot.secrets import MemoryBackend, SecretStore
from tetherbot.ui_settings import (
    HISTORY_MAX_SECONDS,
    POLL_DEFAULT,
    YEAR_SECONDS,
    UiSettings,
    clamp_poll_seconds,
    clamp_undo_seconds,
    effective_poll_seconds,
    effective_undo_seconds,
    history_seconds,
    notice_bot,
)

ROOT = Path(__file__).resolve().parents[1]


def test_poll_and_undo_stay_inside_bounds():
    assert clamp_poll_seconds(120) == 120
    assert clamp_poll_seconds(10) == 60
    assert clamp_poll_seconds(5000) == 900
    assert clamp_poll_seconds(True) == POLL_DEFAULT
    assert clamp_undo_seconds(5) == 5
    assert clamp_undo_seconds(1) == 2
    assert clamp_undo_seconds(90) == 30
    settings = UiSettings(
        poll_seconds=1,
        poll_set=True,
        undo_seconds=0,
        muted_bots=frozenset({"Notes", "primary"}),
        hidden_bots=frozenset({"other"}),
    )
    assert settings.poll_seconds == 60
    assert settings.undo_seconds == 5
    assert settings.muted_bots == frozenset({"primary"})
    assert settings.hidden_bots == frozenset({"other"})


def test_notice_bot_reads_the_id_only():
    assert notice_bot('{"source":{"bot":"primary"},"title":"Hello"}') == "primary"
    assert notice_bot('{"bot":"notes","title":"Re-paste key"}') == "notes"
    assert notice_bot('{"bot":"not a bot"}') == ""
    assert notice_bot("nope") == ""


def test_zero_is_the_default_not_the_minimum():
    assert clamp_poll_seconds(0) == 120
    assert clamp_poll_seconds(-4) == 120
    assert clamp_undo_seconds(0) == 5
    assert effective_poll_seconds(None, None) == 120
    assert effective_poll_seconds(0, 180) == 180
    assert effective_poll_seconds(None, 180) == 180
    assert effective_poll_seconds(200, 180) == 200
    assert effective_poll_seconds(10, 180) == 60
    assert effective_poll_seconds(None, 0) == 120
    assert effective_poll_seconds(None, 5000) == 900
    assert effective_undo_seconds(0) == 5
    assert effective_undo_seconds(None) == 5
    assert effective_undo_seconds(1) == 2
    assert effective_undo_seconds(12) == 12


def test_history_window_uses_fixed_months_and_years():
    assert history_seconds(True, 1, "years") == YEAR_SECONDS
    assert history_seconds(True, 2, "hours") == 7200
    assert history_seconds(True, 2, "weeks") == 14 * 86400
    assert history_seconds(True, 2, "months") == 60 * 86400
    assert history_seconds(False, 1, "years") is None
    assert history_seconds(True, 0, "days") == 86400
    assert history_seconds(True, 1, "nope") == YEAR_SECONDS
    assert history_seconds(True, 5000, "years") == HISTORY_MAX_SECONDS
    settings = UiSettings(history_enabled=True, history_amount=1, history_unit="years")
    assert settings.done_history_seconds == YEAR_SECONDS
    off = UiSettings(history_enabled=False, history_amount=3, history_unit="days")
    assert off.done_history_seconds is None
    assert off.history_amount == 3


def test_schema_defaults_match_the_labels():
    text = (
        ROOT / "extension" / "schemas" / "org.gnome.shell.extensions.tetherbot.gschema.xml"
    ).read_text(encoding="utf-8")
    poll = text.split('name="poll-seconds"', 1)[1].split("</key>", 1)[0]
    undo = text.split('name="undo-seconds"', 1)[1].split("</key>", 1)[0]
    assert "<default>120</default>" in poll
    assert 'min="60"' in poll and 'max="900"' in poll
    assert "<default>5</default>" in undo
    assert 'min="2"' in undo and 'max="30"' in undo
    history = text.split('name="history-enabled"', 1)[1].split("</key>", 1)[0]
    amount = text.split('name="history-amount"', 1)[1].split("</key>", 1)[0]
    unit = text.split('name="history-unit"', 1)[1].split("</key>", 1)[0]
    assert "<default>true</default>" in history
    assert "<default>1</default>" in amount
    assert 'min="1"' in amount and 'max="999"' in amount
    assert "<default>'years'</default>" in unit
    for choice in ("hours", "days", "weeks", "months", "years"):
        assert f'value="{choice}"' in unit


def test_poll_interval_uses_a_saved_setting():
    poller = GitHubPoller()
    ctx = type("Ctx", (), {})()
    ctx.ui_settings = UiSettings(poll_seconds=90, poll_set=True)
    row = type("Row", (), {"poll_seconds": 180})()
    ctx.config = type("Cfg", (), {"adapters": {"github-poller": row}})()
    poller._ctx = ctx
    assert poller._interval() == 90
    ctx.ui_settings = UiSettings()
    assert poller._interval() == 180
    row.poll_seconds = 0
    assert poller._interval() == 120
    ctx.config = None
    assert poller._interval() == 120


def test_save_slot_returns_nothing(tmp_path: Path):
    del tmp_path
    store = SecretStore(MemoryBackend())
    saved = save_slot(
        store,
        "primary-actions",
        "https://hooks.example/hook",
        "super-secret-key",
    )
    assert saved is None
    assert store.get_webhook("primary-actions").key == "super-secret-key"
    assert save_slot(store, "github-token", "", "example-token") is None
    assert store.get_github_token("github-token") == "example-token"


def test_dialog_does_not_launch_without_a_display(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert launch_secret_dialog("primary-actions") is False
    assert launch_secret_dialog("not a slot") is False


def _settings_from_empty_backend(schema_dir: Path) -> dict:
    """Read the compiled file. The session database is not consulted."""

    env = os.environ.copy()
    env["GSETTINGS_BACKEND"] = "memory"
    env["TETHERBOT_SCHEMA_DIR"] = str(schema_dir)
    bridge = str(ROOT / "bridge")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = bridge if not previous else bridge + os.pathsep + previous
    script = "\n".join(
        [
            "import json, os",
            "from pathlib import Path",
            "from tetherbot.ui_settings import load_ui_settings",
            "loaded = load_ui_settings(Path(os.environ['TETHERBOT_SCHEMA_DIR']))",
            "print(json.dumps({",
            "    'poll_seconds': loaded.poll_seconds,",
            "    'poll_set': loaded.poll_set,",
            "    'undo_seconds': loaded.undo_seconds,",
            "    'muted_bots': sorted(loaded.muted_bots),",
            "    'hidden_bots': sorted(loaded.hidden_bots),",
            "    'history_enabled': loaded.history_enabled,",
            "    'history_amount': loaded.history_amount,",
            "    'history_unit': loaded.history_unit,",
            "    'done_history_seconds': loaded.done_history_seconds,",
            "    'clipboard_enabled': loaded.clipboard_enabled,",
            "    'clipboard_images': loaded.clipboard_images,",
            "    'clipboard_limit': loaded.clipboard_limit,",
            "    'clipboard_lookalike': loaded.clipboard_lookalike,",
            "    'clipboard_search_fallback': loaded.clipboard_search_fallback,",
            "    'clipboard_excluded': list(loaded.clipboard_excluded),",
            "}))",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise AssertionError(completed.stdout)
    return payload


def test_compiled_schema_loads_the_defaults(tmp_path: Path):
    if shutil.which("glib-compile-schemas") is None:
        pytest.skip("glib-compile-schemas is not installed")
    dest = tmp_path / "schemas"
    dest.mkdir()
    source = ROOT / "extension" / "schemas" / "org.gnome.shell.extensions.tetherbot.gschema.xml"
    (dest / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["glib-compile-schemas", str(dest)], check=True, timeout=30)
    loaded = _settings_from_empty_backend(dest)
    assert loaded["poll_seconds"] == 120
    assert loaded["poll_set"] is False
    assert loaded["undo_seconds"] == 5
    assert loaded["muted_bots"] == []
    assert loaded["hidden_bots"] == []
    assert loaded["history_enabled"] is True
    assert loaded["history_amount"] == 1
    assert loaded["history_unit"] == "years"
    assert loaded["done_history_seconds"] == YEAR_SECONDS
    assert loaded["clipboard_enabled"] is True
    assert loaded["clipboard_images"] is True
    assert loaded["clipboard_limit"] == 50
    assert loaded["clipboard_lookalike"] == "skip"
    assert loaded["clipboard_search_fallback"].startswith("https://")
    assert "{searchTerms}" in loaded["clipboard_search_fallback"]
    assert "keepassxc" in {name.casefold() for name in loaded["clipboard_excluded"]}
    text = source.read_text(encoding="utf-8")
    folded = text.lower()
    assert "webhook" not in folded
    assert "token" not in folded
    assert "ghp_" not in folded
    assert 'name="clipboard-excluded-apps"' in text
    assert 'name="clipboard-lookalike"' in text
    assert 'name="clipboard-search-fallback"' in text
    assert 'name="clipboard-images"' in text

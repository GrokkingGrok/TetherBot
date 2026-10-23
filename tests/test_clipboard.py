# SPDX-License-Identifier: GPL-2.0-or-later
"""Clipboard history stays local, and sensitive copies are not stored."""

import json
import shutil
import stat
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import NOW
from tetherbot.clipboard_policy import (
    DEFAULT_EXCLUDED_APPS,
    classify_clipboard,
)
from tetherbot.clipboard_store import ClipboardHistory
from tetherbot.daemon import BridgeDaemon
from tetherbot.service import ServiceError
from tetherbot.ui_settings import UiSettings

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "sample clipboard line"
META = json.dumps({"mimes": ["text/plain"], "wm_class": "gedit"})


def _history(tmp_path: Path, **kwargs: object) -> ClipboardHistory:
    return ClipboardHistory(
        tmp_path / "state" / "clipboard.json",
        clock=lambda: 1_700_000_000,
        **kwargs,
    )


def test_plain_text_is_stored_and_a_repeat_moves_forward(tmp_path: Path):
    history = _history(tmp_path)
    assert history.offer("first", ["text/plain"], "gedit") == "stored"
    first_id = history.list_entries()[0]["id"]
    assert history.offer("second", ["text/plain"], "gedit") == "stored"
    assert history.offer("first", ["text/plain"], "gedit") == "stored"
    assert [row["text"] for row in history.list_entries()] == ["first", "second"]
    assert history.list_entries()[0]["id"] == first_id
    mode = history.path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR
    assert history.path.parent.stat().st_mode & 0o777 == 0o700
    payload = json.loads(history.path.read_text(encoding="utf-8"))
    assert payload["kind"] == "clipboard"
    assert "schema" not in payload


def test_sensitive_and_excluded_copies_are_not_stored(tmp_path: Path):
    history = _history(tmp_path)
    hint = history.offer(
        "not-stored",
        ["text/plain", "x-kde-passwordManagerHint"],
        "org.keepassxc.KeePassXC",
    )
    assert hint == "skipped-sensitive"
    concealed = history.offer(
        "not-stored",
        ["application/x-nspasteboard-concealed-type"],
        "gedit",
    )
    assert concealed == "skipped-sensitive"
    excluded = history.offer("not-stored", ["text/plain"], "org.keepassxc.KeePassXC")
    assert excluded == "skipped-app"
    mixed = history.offer("not-stored", ["text/plain"], "1Password")
    assert mixed == "skipped-app"
    assert history.offer("not-stored", ["image/png"], "gedit") == "skipped-binary"
    assert history.offer("   ", ["text/plain"], "gedit") == "skipped-empty"
    assert history.offer("x" * 20, ["text/plain"], "gedit") == "stored"
    assert [row["text"] for row in history.list_entries()] == ["x" * 20]
    assert not history.path.exists() or "not-stored" not in history.path.read_text(encoding="utf-8")


def test_classify_skips_sensitive_marks_before_text_is_required():
    assert (
        classify_clipboard(
            None,
            ["text/plain", "x-kde-passwordManagerHint"],
            "gedit",
            enabled=True,
            excluded=DEFAULT_EXCLUDED_APPS,
        )
        == "skipped-sensitive"
    )
    assert (
        classify_clipboard(
            None,
            ["text/plain"],
            "org.gnome.World.Secrets",
            enabled=True,
            excluded=DEFAULT_EXCLUDED_APPS,
        )
        == "skipped-app"
    )
    plain = classify_clipboard(
        None,
        ["text/plain"],
        "gedit",
        enabled=True,
        excluded=DEFAULT_EXCLUDED_APPS,
    )
    assert plain == "needs-text"
    assert (
        classify_clipboard("hello", ["text/plain"], "gedit", enabled=False, excluded=())
        == "skipped-disabled"
    )


def test_toggle_off_keeps_old_entries_and_the_cap_trims(tmp_path: Path):
    history = _history(tmp_path, limit=2)
    assert history.offer("one", ["text/plain"], "gedit") == "stored"
    assert history.offer("two", ["text/plain"], "gedit") == "stored"
    assert history.offer("three", ["text/plain"], "gedit") == "stored"
    assert [row["text"] for row in history.list_entries()] == ["three", "two"]
    history.configure(enabled=False, limit=2, excluded=DEFAULT_EXCLUDED_APPS)
    assert history.offer("four", ["text/plain"], "gedit") == "skipped-disabled"
    assert [row["text"] for row in history.list_entries()] == ["three", "two"]
    assert history.list_entries("TWO")[0]["text"] == "two"
    ident = history.list_entries()[0]["id"]
    assert history.delete(ident) is True
    assert [row["text"] for row in history.list_entries()] == ["two"]
    assert history.clear() is True
    assert history.list_entries() == []


def test_history_is_not_written_beside_the_clipboard_file(tmp_path: Path):
    feed = tmp_path / "feed"
    desktop = tmp_path / "desktop"
    feed.mkdir()
    desktop.mkdir()
    history = _history(tmp_path)
    assert history.offer(SAMPLE, ["text/plain"], "gedit") == "stored"
    assert list(feed.iterdir()) == []
    assert list(desktop.iterdir()) == []
    hits = [
        path.name
        for path in tmp_path.rglob("*")
        if path.is_file() and SAMPLE in path.read_text(encoding="utf-8")
    ]
    assert hits == ["clipboard.json"]


def test_service_offer_filters_and_does_not_log_the_text(tmp_path: Path):
    stream = StringIO()
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=stream,
        clock=lambda: NOW,
    )
    daemon.start()
    assert daemon.api is not None
    seen: list[tuple[str, tuple[object, ...]]] = []
    daemon.api.subscribe(lambda name, args: seen.append((name, args)))
    stored = daemon.api.call("OfferClipboard", (SAMPLE, META))
    assert stored == ("stored",)
    assert ("ClipboardChanged", (1,)) in seen
    listed = json.loads(daemon.api.call("GetClipboard", ("sample",))[0])
    assert [row["text"] for row in listed] == [SAMPLE]
    hint = json.dumps({"mimes": ["x-kde-passwordManagerHint"], "wm_class": "keepassxc"})
    skipped = daemon.api.call("OfferClipboard", ("not-stored", hint))
    assert skipped == ("skipped-sensitive",)
    assert json.loads(daemon.api.call("GetClipboard", ("",))[0])[0]["text"] == SAMPLE
    daemon.ui_settings = UiSettings(clipboard_enabled=False)
    assert daemon.api.call("OfferClipboard", ("later", META)) == ("skipped-disabled",)
    assert daemon.api.call("ClearClipboard", ()) == (True,)
    assert json.loads(daemon.api.call("GetClipboard", ("",))[0]) == []
    assert SAMPLE not in stream.getvalue()
    assert "not-stored" not in stream.getvalue()
    with pytest.raises(ServiceError):
        daemon.api.call("OfferClipboard", (SAMPLE, "not-json"))


def test_javascript_filter_matches_the_bridge():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    subprocess.run(
        [node, "extension/clipboard_checks.js"],
        check=True,
        cwd=ROOT,
        timeout=30,
    )

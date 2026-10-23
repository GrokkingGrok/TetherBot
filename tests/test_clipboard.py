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
    format_clipboard_debug,
    looks_like_password,
)
from tetherbot.clipboard_store import ClipboardHistory
from tetherbot.daemon import BridgeDaemon
from tetherbot.service import ServiceError
from tetherbot.todos import tag_color
from tetherbot.ui_settings import UiSettings

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = "sample clipboard line"
META = json.dumps({"mimes": ["text/plain"], "wm_class": "gedit"})
LOOKALIKE = "aB3!xxxx"
CHROME_MIMES = [
    "text/plain",
    "text/plain;charset=utf-8",
    "UTF8_STRING",
    "STRING",
    "TEXT",
    "chromium/x-source-url",
]


def _history(tmp_path: Path, **kwargs: object) -> ClipboardHistory:
    clock = kwargs.pop("clock", lambda: 1_700_000_000)
    return ClipboardHistory(
        tmp_path / "state" / "clipboard.json",
        clock=clock,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
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


def test_a_password_lookalike_is_skipped_and_not_written(tmp_path: Path):
    history = _history(tmp_path)
    assert looks_like_password(LOOKALIKE) is True
    assert looks_like_password("C0rrect-Horse") is True
    assert looks_like_password("Password1") is True
    assert looks_like_password("hello world") is False
    assert looks_like_password("https://example.com/notes") is False
    assert looks_like_password("/home/user/notes") is False
    assert looks_like_password("12345678") is False
    assert looks_like_password("hello") is False
    assert looks_like_password("HelloWorld") is False
    assert looks_like_password("README.md") is False
    assert looks_like_password("User@example.com") is False
    assert looks_like_password("password1") is False
    assert looks_like_password("550e8400-e29b-41d4-a716-446655440000") is False
    assert looks_like_password(LOOKALIKE + "\n") is True
    assert (
        classify_clipboard(
            None,
            CHROME_MIMES,
            "google-chrome",
            enabled=True,
            excluded=(),
        )
        == "needs-text"
    )
    assert (
        classify_clipboard(
            None,
            [*CHROME_MIMES, "application/x-chromium-password-sensitive"],
            "google-chrome",
            enabled=True,
            excluded=(),
        )
        == "skipped-sensitive"
    )
    assert (
        classify_clipboard(
            LOOKALIKE,
            CHROME_MIMES,
            "Google-Chrome",
            enabled=True,
            excluded=(),
        )
        == "skipped-lookalike"
    )
    assert history.offer(LOOKALIKE, CHROME_MIMES, "google-chrome") == "skipped-lookalike"
    assert history.offer("hello world", CHROME_MIMES, "chromium") == "stored"
    blob = history.path.read_text(encoding="utf-8")
    assert LOOKALIKE not in blob
    report = format_clipboard_debug(json.loads(blob))
    assert report.startswith("result: stored\n")
    assert "text/plain" in report
    assert "chromium/x-source-url" in report
    assert LOOKALIKE not in report
    history.offer(LOOKALIKE, CHROME_MIMES, "Google-Chrome")
    report = format_clipboard_debug(json.loads(history.path.read_text(encoding="utf-8")))
    assert "result: skipped-lookalike" in report
    assert "reason: password lookalike" in report
    assert "Google-Chrome" in report
    assert LOOKALIKE not in report
    assert "hello world" not in report


def test_mask_mode_hides_a_lookalike_and_drops_it_after_30_seconds(tmp_path: Path):
    now = {"t": 1_700_000_000}
    history = _history(tmp_path, lookalike="mask", clock=lambda: now["t"])
    assert history.offer(LOOKALIKE, CHROME_MIMES, "google-chrome") == "stored-masked"
    listed = history.list_entries()
    assert listed[0]["masked"] is True
    assert listed[0]["text"] == LOOKALIKE
    assert history.list_entries(LOOKALIKE) == []
    report = format_clipboard_debug(json.loads(history.path.read_text(encoding="utf-8")))
    assert "result: stored-masked" in report
    assert "reason: hidden for 30 seconds" in report
    assert LOOKALIKE not in report
    now["t"] += 29
    assert history.list_entries()[0]["text"] == LOOKALIKE
    now["t"] += 1
    assert history.list_entries() == []
    assert LOOKALIKE not in history.path.read_text(encoding="utf-8")
    assert history.offer(LOOKALIKE, ["text/plain"], "gedit") == "stored-masked"
    history.configure(enabled=True, limit=50, excluded=(), lookalike="skip")
    assert history.list_entries() == []
    assert LOOKALIKE not in history.path.read_text(encoding="utf-8")


def test_note_records_mimes_without_the_text(tmp_path: Path):
    stream = StringIO()
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=stream,
        clock=lambda: NOW,
    )
    daemon.start()
    assert daemon.api is not None
    note = json.dumps(
        {
            "mimes": CHROME_MIMES,
            "wm_class": "google-chrome",
            "result": "skipped-lookalike",
            "text": LOOKALIKE,
        }
    )
    assert daemon.api.call("NoteClipboard", (note,)) == (True,)
    blob = (tmp_path / "state" / "clipboard.json").read_text(encoding="utf-8")
    assert LOOKALIKE not in blob
    assert LOOKALIKE not in stream.getvalue()
    report = format_clipboard_debug(json.loads(blob))
    assert "skipped-lookalike" in report
    assert "text/plain" in report
    assert "google-chrome" in report
    with pytest.raises(ServiceError):
        daemon.api.call(
            "NoteClipboard",
            (json.dumps({"mimes": ["text/plain"], "wm_class": "gedit", "result": LOOKALIKE}),),
        )
    assert LOOKALIKE not in stream.getvalue()
    daemon.ui_settings = UiSettings(clipboard_lookalike="mask")
    assert daemon.api.call("OfferClipboard", (LOOKALIKE, META)) == ("stored-masked",)
    listed = json.loads(daemon.api.call("GetClipboard", ("",))[0])
    assert listed[0]["masked"] is True
    assert json.loads(daemon.api.call("GetClipboard", (LOOKALIKE,))[0]) == []
    assert LOOKALIKE not in stream.getvalue()


def test_pin_survives_the_cap_and_clear_and_tags_are_searchable(tmp_path: Path):
    history = _history(tmp_path, limit=2)
    assert history.offer("one", ["text/plain"], "gedit") == "stored"
    assert history.offer("two", ["text/plain"], "gedit") == "stored"
    assert history.offer("three", ["text/plain"], "gedit") == "stored"
    oldest = next(row for row in history.list_entries() if row["text"] == "two")
    assert history.set_pinned(oldest["id"], True) is True
    assert history.offer("four", ["text/plain"], "gedit") == "stored"
    texts = [row["text"] for row in history.list_entries()]
    assert texts[0] == "two"
    assert "two" in texts
    assert len([row for row in history.list_entries() if not row["pinned"]]) == 2
    assert history.set_tags(oldest["id"], [{"name": "Later", "color": "nope"}, "later"]) is True
    tagged = history.list_entries()[0]
    assert tagged["pinned"] is True
    assert tagged["tags"] == [{"name": "Later", "color": tag_color("Later")}]
    assert history.list_entries("later")[0]["id"] == oldest["id"]
    assert history.edit_text(oldest["id"], "two\nkept") is True
    edited = history.list_entries()[0]
    assert edited["text"] == "two\nkept"
    assert edited["pinned"] is True
    assert edited["tags"][0]["name"] == "Later"
    assert history.clear() is True
    left = history.list_entries()
    assert [row["text"] for row in left] == ["two\nkept"]
    assert left[0]["pinned"] is True
    blob = history.path.read_text(encoding="utf-8")
    assert "four" not in blob
    assert "two\\nkept" in blob or "two\nkept" in blob


def test_old_clipboard_file_loads_and_a_hidden_password_is_not_edited(tmp_path: Path):
    path = tmp_path / "state" / "clipboard.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "kind": "clipboard",
                "entries": [
                    {"id": "c-1234abcd", "text": "kept line", "at": 5, "extra": "ignore"},
                    {
                        "id": "c-1234abce",
                        "text": LOOKALIKE,
                        "at": 6,
                        "masked": True,
                        "until": 1_700_000_100,
                        "pinned": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    history = ClipboardHistory(path, clock=lambda: 1_700_000_000)
    rows = history.list_entries()
    assert [row["text"] for row in rows] == [LOOKALIKE, "kept line"]
    assert rows[0]["pinned"] is True
    assert rows[1]["pinned"] is False
    assert rows[1]["tags"] == []
    kept = next(row for row in history.entries if row["text"] == "kept line")
    assert "extra" not in kept
    assert "extra" in path.read_text(encoding="utf-8")
    assert history.edit_text(rows[0]["id"], "changed") is False
    assert history.list_entries()[0]["text"] == LOOKALIKE
    history.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert all("extra" not in row for row in saved["entries"])
    assert path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR


def test_service_pin_edit_and_tags_do_not_log_text(tmp_path: Path):
    stream = StringIO()
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=stream,
        clock=lambda: NOW,
    )
    daemon.start()
    assert daemon.api is not None
    assert daemon.api.call("OfferClipboard", ("alpha line", META)) == ("stored",)
    ident = json.loads(daemon.api.call("GetClipboard", ("",))[0])[0]["id"]
    assert daemon.api.call("PinClipboard", (ident, True)) == (True,)
    assert daemon.api.call("SetClipboardTags", (ident, '[{"name":"notes","color":"teal"}]')) == (
        True,
    )
    found = json.loads(daemon.api.call("GetClipboard", ("notes",))[0])
    assert found[0]["text"] == "alpha line"
    assert daemon.api.call("EditClipboard", (ident, "alpha\nline")) == (True,)
    assert json.loads(daemon.api.call("GetClipboard", ("",))[0])[0]["pinned"] is True
    daemon.ui_settings = UiSettings(clipboard_lookalike="mask")
    assert daemon.api.call("OfferClipboard", (LOOKALIKE, META)) == ("stored-masked",)
    hidden = next(
        row
        for row in json.loads(daemon.api.call("GetClipboard", ("",))[0])
        if row.get("masked") is True
    )
    assert daemon.api.call("EditClipboard", (hidden["id"], "changed")) == (False,)
    assert LOOKALIKE not in stream.getvalue()
    assert "alpha line" not in stream.getvalue()
    with pytest.raises(ServiceError):
        daemon.api.call("SetClipboardTags", (ident, LOOKALIKE))


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

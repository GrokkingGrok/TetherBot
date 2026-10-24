# SPDX-License-Identifier: GPL-2.0-or-later
"""Clipboard history stays local, and sensitive copies are not stored."""

import json
import shutil
import stat
import struct
import subprocess
import zlib
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import NOW
from tetherbot.clipboard_policy import (
    DEFAULT_EXCLUDED_APPS,
    IMAGE_COUNT_MAX,
    IMAGE_MAX_BYTES,
    classify_clipboard,
    classify_image,
    format_clipboard_debug,
    image_label,
    looks_like_password,
    pick_image_mime,
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
    assert "kind" not in kept
    assert "extra" in path.read_text(encoding="utf-8")
    assert history.edit_text(rows[0]["id"], "changed") is False
    assert history.list_entries()[0]["text"] == LOOKALIKE
    history.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert all("extra" not in row for row in saved["entries"])
    assert path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR


def test_pin_toggles_keep_an_image_among_text(tmp_path: Path):
    history = _history(tmp_path)
    assert history.offer("alpha line", ["text/plain"], "gedit") == "stored"
    assert history.offer("beta line", ["text/plain"], "gedit") == "stored"
    blob = tiny_png(4, 5, 6)
    assert history.offer_image(blob, ["image/png"], "gedit", "image/png") == "stored"
    listed = history.list_entries()
    image = next(row for row in listed if row.get("kind") == "image")
    text_ids = [row["id"] for row in listed if row.get("kind") != "image"]
    path = Path(image["path"])
    assert path.is_file()
    assert len(text_ids) == 2
    for pinned in (True, False, True, False):
        assert history.set_pinned(image["id"], pinned) is True
        history.configure(
            enabled=True,
            limit=50,
            excluded=DEFAULT_EXCLUDED_APPS,
            lookalike="skip",
            images=True,
        )
        again = history.list_entries()
        ids = [row["id"] for row in again]
        assert image["id"] in ids
        assert set(text_ids) <= set(ids)
        kept = next(row for row in again if row["id"] == image["id"])
        assert kept["kind"] == "image"
        assert kept["pinned"] is pinned
        assert path.is_file()
        assert blob == path.read_bytes()


def test_a_hidden_password_can_be_pinned_but_not_tagged(tmp_path: Path):
    now = {"at": 1_700_000_000}
    history = _history(tmp_path, lookalike="mask", clock=lambda: now["at"])
    assert history.offer(LOOKALIKE, ["text/plain"], "gedit") == "stored-masked"
    row = history.list_entries()[0]
    assert history.set_pinned(row["id"], True) is True
    assert history.set_tags(row["id"], [{"name": "Later", "color": "blue"}]) is False
    listed = history.list_entries()
    assert listed[0]["pinned"] is True
    assert listed[0]["tags"] == []
    assert "Later" not in history.path.read_text(encoding="utf-8")
    now["at"] = 1_700_000_031
    assert history.purge() is True
    assert history.list_entries() == []


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


def test_search_clipboard_opens_text_and_skips_images(tmp_path: Path, monkeypatch):
    launched: list[str] = []

    def opened(text, fallback, home=None):
        launched.append(text if isinstance(text, str) else "")
        assert isinstance(fallback, str) and fallback.startswith("https://")
        assert home is None
        return "opened"

    monkeypatch.setattr("tetherbot.clipboard_search.open_clip_search", opened)
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
    assert daemon.api.call("SearchClipboard", (ident,)) == (True,)
    assert launched == ["alpha line"]
    blob = tiny_png(1, 2, 3)
    meta = json.dumps({"mimes": ["image/png"], "wm_class": "gedit", "mime": "image/png"})
    assert daemon.api.call("OfferClipboardImage", (blob, meta)) == ("stored",)
    image = next(
        row
        for row in json.loads(daemon.api.call("GetClipboard", ("",))[0])
        if row.get("kind") == "image"
    )
    assert daemon.api.call("SearchClipboard", (image["id"],)) == (False,)
    daemon.ui_settings = UiSettings(clipboard_lookalike="mask")
    assert daemon.api.call("OfferClipboard", (LOOKALIKE, META)) == ("stored-masked",)
    hidden = next(
        row
        for row in json.loads(daemon.api.call("GetClipboard", ("",))[0])
        if row.get("masked") is True
    )
    assert daemon.api.call("SearchClipboard", (hidden["id"],)) == (False,)
    assert daemon.api.call("SearchClipboard", ("c-00000000",)) == (False,)
    assert launched == ["alpha line"]
    logged = stream.getvalue()
    assert "alpha line" not in logged
    assert "duckduckgo" not in logged
    assert LOOKALIKE not in logged
    with pytest.raises(ServiceError):
        daemon.api.call("SearchClipboard", ("not-an-id",))


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def tiny_png(red: int = 255, green: int = 0, blue: int = 0, note: bytes = b"") -> bytes:
    """A 1x1 PNG. ``note`` is stored in a text chunk so tests can spot a leak."""

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(bytes((0, red, green, blue)))
    parts = [signature, _png_chunk(b"IHDR", header)]
    if note:
        parts.append(_png_chunk(b"tEXt", b"Comment\x00" + note))
    parts.append(_png_chunk(b"IDAT", pixels))
    parts.append(_png_chunk(b"IEND", b""))
    return b"".join(parts)


def test_pick_image_mime_lets_plain_text_win():
    assert pick_image_mime(["image/png"]) == "image/png"
    assert pick_image_mime(["image/jpeg", "image/png"]) == "image/png"
    assert pick_image_mime(["text/html", "image/jpeg"]) == "image/jpeg"
    assert pick_image_mime(["text/plain", "image/png"]) is None
    assert pick_image_mime(["UTF8_STRING", "image/webp"]) is None
    assert pick_image_mime(["image/jpg"]) == "image/jpeg"
    assert image_label("image/png", 1_258_291) == "Image · PNG · 1.2 MB"
    assert (
        classify_image(
            ["image/png", "x-kde-passwordManagerHint"],
            "gedit",
            "image/png",
            12,
            enabled=True,
            images=True,
            excluded=DEFAULT_EXCLUDED_APPS,
        )
        == "skipped-sensitive"
    )
    assert (
        classify_image(
            ["image/png"],
            "org.keepassxc.KeePassXC",
            "image/png",
            12,
            enabled=True,
            images=True,
            excluded=DEFAULT_EXCLUDED_APPS,
        )
        == "skipped-app"
    )
    assert (
        classify_image(
            ["image/png"],
            "gedit",
            "image/png",
            12,
            enabled=True,
            images=False,
            excluded=(),
        )
        == "skipped-images-off"
    )


def test_an_image_is_stored_once_with_a_private_file(tmp_path: Path):
    history = _history(tmp_path)
    blob = tiny_png(note=b"marker-not-searched")
    meta_mimes = ["image/png"]
    assert history.offer_image(blob, meta_mimes, "gedit", "image/png") == "stored"
    assert history.offer_image(blob, meta_mimes, "gedit", "image/png") == "stored"
    listed = history.list_entries()
    assert len(listed) == 1
    row = listed[0]
    assert row["kind"] == "image"
    assert row["mime"] == "image/png"
    assert row["size"] == len(blob)
    assert row["width"] == 1
    assert row["height"] == 1
    assert row["text"] == ""
    path = Path(row["path"])
    assert path.is_file()
    assert path.read_bytes() == blob
    assert path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR
    assert history.image_dir.stat().st_mode & 0o777 == 0o700
    images = [
        item
        for item in history.image_dir.iterdir()
        if item.suffix == ".png" and ".thumb." not in item.name
    ]
    assert images == [path]
    saved = history.path.read_text(encoding="utf-8")
    assert '"kind":"image"' in saved
    assert '"mime":"image/png"' in saved
    assert "clipboard-images" not in saved
    assert "marker-not-searched" not in saved
    assert blob not in history.path.read_bytes()
    assert history.list_entries("image")[0]["id"] == row["id"]
    assert history.list_entries("marker-not-searched") == []
    assert history.list_entries("png")[0]["id"] == row["id"]


def test_bad_images_are_rejected_without_a_file(tmp_path: Path):
    history = _history(tmp_path)
    blob = tiny_png()
    assert history.offer_image(b"hello", ["text/plain"], "gedit", "text/plain") == "skipped-binary"
    assert history.offer_image(blob, ["text/plain", "image/png"], "gedit", "image/png") == (
        "skipped-binary"
    )
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * IMAGE_MAX_BYTES
    assert history.offer_image(huge, ["image/png"], "gedit", "image/png") == "skipped-image-large"
    wide = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 9000, 1, 8, 2, 0, 0, 0))
    wide_png = b"\x89PNG\r\n\x1a\n" + wide + _png_chunk(b"IEND", b"")
    assert history.offer_image(wide_png, ["image/png"], "gedit", "image/png") == (
        "skipped-image-large"
    )
    corrupt = tiny_png()[:24] + _png_chunk(b"IDAT", b"not-zlib") + _png_chunk(b"IEND", b"")
    assert history.offer_image(corrupt, ["image/png"], "gedit", "image/png") == "skipped-image-bad"
    hint = ["image/png", "x-kde-passwordManagerHint"]
    assert history.offer_image(blob, hint, "gedit", "image/png") == "skipped-sensitive"
    assert history.offer_image(blob, ["image/png"], "1Password", "image/png") == "skipped-app"
    assert history.list_entries() == []
    assert not history.image_dir.exists()
    report = format_clipboard_debug(json.loads(history.path.read_text(encoding="utf-8")))
    assert "result: skipped-app" in report
    assert "reason: excluded app" in report
    assert "image/png" in report
    assert "clipboard-images" not in report
    quiet = _history(tmp_path / "off", images=False)
    assert quiet.offer_image(blob, ["image/png"], "gedit", "image/png") == "skipped-images-off"
    assert quiet.offer("still text", ["text/plain"], "gedit") == "stored"
    assert not quiet.image_dir.exists()
    off = format_clipboard_debug(json.loads(quiet.path.read_text(encoding="utf-8")))
    assert "reason: images-off" not in off
    quiet.offer_image(blob, ["image/png"], "gedit", "image/png")
    off = format_clipboard_debug(json.loads(quiet.path.read_text(encoding="utf-8")))
    assert "result: skipped-images-off" in off
    assert "reason: images-off" in off


def test_image_caps_unlink_files_and_a_pin_survives(tmp_path: Path):
    limited = _history(tmp_path / "limit", limit=2)
    first = tiny_png(1, 0, 0)
    assert limited.offer_image(first, ["image/png"], "gedit", "image/png") == "stored"
    oldest = Path(limited.list_entries()[0]["path"])
    assert limited.offer_image(tiny_png(2, 0, 0), ["image/png"], "gedit", "image/png") == "stored"
    assert limited.offer_image(tiny_png(3, 0, 0), ["image/png"], "gedit", "image/png") == "stored"
    assert len(limited.list_entries()) == 2
    assert not oldest.exists()

    history = _history(tmp_path / "count", limit=500)
    blobs = [tiny_png(index, 2, 3) for index in range(IMAGE_COUNT_MAX + 1)]
    for blob in blobs:
        assert history.offer_image(blob, ["image/png"], "gedit", "image/png") == "stored"
    assert len(history.list_entries()) == IMAGE_COUNT_MAX
    names = {path.name for path in history.image_dir.iterdir() if ".thumb." not in path.name}
    assert len(names) == IMAGE_COUNT_MAX
    pinned_blob = tiny_png(9, 9, 9)
    assert history.offer_image(pinned_blob, ["image/png"], "gedit", "image/png") == "stored"
    pinned = history.list_entries()[0]
    pinned_path = Path(pinned["path"])
    assert history.set_pinned(pinned["id"], True) is True
    assert history.set_tags(pinned["id"], [{"name": "Shot", "color": "nope"}]) is True
    assert history.edit_text(pinned["id"], "nope") is False
    for index in range(IMAGE_COUNT_MAX):
        assert history.offer_image(tiny_png(index, 4, 5), ["image/png"], "gedit", "image/png") == (
            "stored"
        )
    kept = history.list_entries()
    assert kept[0]["id"] == pinned["id"]
    assert kept[0]["pinned"] is True
    assert kept[0]["tags"][0]["name"] == "Shot"
    assert pinned_path.is_file()
    assert history.clear() is True
    left = history.list_entries()
    assert [row["id"] for row in left] == [pinned["id"]]
    assert pinned_path.is_file()
    assert history.delete(pinned["id"]) is True
    assert not pinned_path.is_file()
    assert history.list_entries() == []
    thumbs = list(history.image_dir.glob("*.thumb.png")) if history.image_dir.exists() else []
    assert thumbs == []


def test_load_drops_a_missing_image_and_deletes_orphans(tmp_path: Path):
    history = _history(tmp_path)
    blob = tiny_png(4, 5, 6)
    assert history.offer_image(blob, ["image/png"], "gedit", "image/png") == "stored"
    path = Path(history.list_entries()[0]["path"])
    orphan = history.image_dir / "c-abcdef01.png"
    orphan.write_bytes(b"orphan-bytes")
    missing = history.image_dir / "c-abcdef02.png"
    path.rename(missing)
    reloaded = ClipboardHistory(history.path, clock=lambda: 1_700_000_000)
    assert reloaded.list_entries() == []
    assert not orphan.exists()
    assert not missing.exists()
    assert history.offer("kept line", ["text/plain"], "gedit") == "stored"
    text_only = ClipboardHistory(history.path, clock=lambda: 1_700_000_000)
    assert [row["text"] for row in text_only.list_entries()] == ["kept line"]
    assert "kind" not in text_only.entries[0]


def test_an_image_offer_does_not_log_bytes_or_the_path(tmp_path: Path):
    stream = StringIO()
    feed = tmp_path / "feed"
    desktop = tmp_path / "desktop"
    feed.mkdir()
    desktop.mkdir()
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=stream,
        clock=lambda: NOW,
    )
    daemon.start()
    assert daemon.clipboard is not None
    blob = tiny_png(note=b"marker-not-logged")
    assert daemon.clipboard.offer_image(blob, ["image/png"], "gedit", "image/png") == "stored"
    logged = stream.getvalue()
    log_path = tmp_path / "state" / "bridge.log"
    disk = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    assert "marker-not-logged" not in logged
    assert "clipboard-images" not in logged
    assert "marker-not-logged" not in disk
    assert "clipboard-images" not in disk
    assert blob not in logged.encode()
    hits = [
        path.name
        for path in tmp_path.rglob("*")
        if path.is_file() and blob in path.read_bytes()
    ]
    assert hits
    assert all(name.endswith(".png") and ".thumb." not in name for name in hits)
    assert list(feed.iterdir()) == []
    assert list(desktop.iterdir()) == []


def test_service_stores_an_image_and_honors_images_off(tmp_path: Path):
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
    blob = tiny_png(note=b"marker-not-logged")
    meta = json.dumps({"mimes": ["image/png"], "wm_class": "gedit", "mime": "image/png"})
    assert daemon.api.call("OfferClipboardImage", (blob, meta)) == ("stored",)
    assert ("ClipboardChanged", (1,)) in seen
    listed = json.loads(daemon.api.call("GetClipboard", ("",))[0])
    assert listed[0]["kind"] == "image"
    ident = listed[0]["id"]
    mime, data = daemon.api.call("GetClipboardImage", (ident,))
    assert mime == "image/png"
    assert data == blob
    assert daemon.api.call("EditClipboard", (ident, "changed")) == (False,)
    hint = json.dumps(
        {
            "mimes": ["image/png", "x-kde-passwordManagerHint"],
            "wm_class": "gedit",
            "mime": "image/png",
        }
    )
    assert daemon.api.call("OfferClipboardImage", (blob, hint)) == ("skipped-sensitive",)
    excluded = json.dumps({"mimes": ["image/png"], "wm_class": "keepassxc", "mime": "image/png"})
    assert daemon.api.call("OfferClipboardImage", (blob, excluded)) == ("skipped-app",)
    daemon.ui_settings = UiSettings(clipboard_images=False)
    fresh = tiny_png(1, 2, 3)
    assert daemon.api.call("OfferClipboardImage", (fresh, meta)) == ("skipped-images-off",)
    assert daemon.api.call("OfferClipboard", ("still text", META)) == ("stored",)
    rows = json.loads(daemon.api.call("GetClipboard", ("",))[0])
    assert [row.get("text") for row in rows] == ["still text", ""]
    assert sum(1 for row in rows if row.get("kind") == "image") == 1
    logged = stream.getvalue()
    log_path = tmp_path / "state" / "bridge.log"
    disk = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    assert "marker-not-logged" not in logged
    assert "clipboard-images" not in logged
    assert "marker-not-logged" not in disk
    assert "clipboard-images" not in disk
    assert blob not in logged.encode()
    with pytest.raises(ServiceError):
        daemon.api.call("OfferClipboardImage", ("nope", meta))
    with pytest.raises(ServiceError):
        daemon.api.call("OfferClipboardImage", (blob, "not-json"))
    with pytest.raises(ServiceError):
        daemon.api.call("GetClipboardImage", ("c-00000000",))


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

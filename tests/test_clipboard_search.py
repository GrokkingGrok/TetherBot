# SPDX-License-Identifier: GPL-2.0-or-later
"""Search URLs come from the desktop's saved engine, or from nowhere."""

import json
import sqlite3
from pathlib import Path

from tetherbot.clipboard_policy import list_preview
from tetherbot.clipboard_search import (
    FALLBACK_SEARCH_TEMPLATE,
    choose_search_template,
    decode_mozlz4,
    discover_search_template,
    normalize_search_url,
    search_target,
    template_from_chromium,
    template_from_firefox,
    template_from_web_data,
)


def test_list_preview_keeps_one_line_and_shortens_a_long_item():
    assert list_preview("one\ntwo") == "one two"
    long = "word " * 50
    preview = list_preview(long)
    assert "\n" not in preview
    assert len(preview) <= 180
    assert preview.endswith("…")


def test_search_target_uses_the_template_and_rejects_a_missing_engine():
    template = "https://example.test/search?q={searchTerms}"
    assert search_target("hello world", template) == "https://example.test/search?q=hello%20world"
    assert search_target("   ", template) is None
    assert search_target("hello", None) is None
    assert search_target("hello", "http://example.test/?q={searchTerms}") is None
    assert search_target("hello", "https://example.test/search") is None
    chrome = {
        "default_search_provider_data": {
            "template_url_data": {
                "url": "{google:baseURL}search?q={searchTerms}&{google:RLZ}ie={inputEncoding}",
            }
        }
    }
    assert template_from_chromium(chrome) == "https://www.google.com/search?q={searchTerms}&ie=UTF-8"
    legacy = {"default_search_provider": {"search_url": "https://example.test/?q=%s"}}
    assert template_from_chromium(legacy) == "https://example.test/?q=%s"
    assert normalize_search_url("not a url") is None


def test_firefox_template_is_read_from_the_profile(tmp_path: Path):
    payload = {
        "engines": [
            {
                "id": "example",
                "_urls": [
                    {
                        "template": "https://example.test/search",
                        "params": [{"name": "q", "value": "{searchTerms}"}],
                    }
                ],
            }
        ],
        "metaData": {"defaultEngineId": "example"},
    }
    raw = json.dumps(payload).encode("utf-8")
    profile = tmp_path / ".mozilla" / "firefox" / "abc"
    profile.mkdir(parents=True)
    (tmp_path / ".mozilla" / "firefox" / "profiles.ini").write_text(
        "[Profile0]\nPath=abc\nIsRelative=1\nDefault=1\n",
        encoding="utf-8",
    )
    (profile / "search.json.mozlz4").write_bytes(_mozlz4(raw))
    found = discover_search_template(tmp_path, "firefox.desktop")
    assert found == "https://example.test/search?q={searchTerms}"
    assert search_target("notes", found) == "https://example.test/search?q=notes"
    assert discover_search_template(tmp_path, "unknown.desktop") is None
    assert template_from_firefox(payload) == found
    assert decode_mozlz4(b"not-a-blob") is None


def test_chromium_https_template_is_read_from_preferences(tmp_path: Path):
    root = tmp_path / ".config" / "google-chrome" / "Default"
    root.mkdir(parents=True)
    (root / "Preferences").write_text(
        json.dumps(
            {
                "default_search_provider_data": {
                    "template_url_data": {
                        "url": "https://example.test/find?q={searchTerms}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    found = discover_search_template(tmp_path, "google-chrome.desktop")
    assert found == "https://example.test/find?q={searchTerms}"
    chosen, kind = choose_search_template(tmp_path, "unknown.desktop")
    assert chosen == FALLBACK_SEARCH_TEMPLATE
    assert kind == "fallback"
    assert choose_search_template(tmp_path, "unknown.desktop", None, "nope") == (None, "none")
    browser, browser_kind = choose_search_template(
        tmp_path,
        "google-chrome.desktop",
        None,
        FALLBACK_SEARCH_TEMPLATE,
    )
    assert browser == found
    assert browser_kind == "browser"


def test_chrome_reads_the_last_used_profile_and_web_data(tmp_path: Path):
    root = tmp_path / ".config" / "google-chrome"
    default = root / "Default"
    other = root / "Profile 1"
    default.mkdir(parents=True)
    other.mkdir()
    (root / "Local State").write_text(
        json.dumps({"profile": {"last_used": "Profile 1"}}),
        encoding="utf-8",
    )
    (default / "Preferences").write_text(
        json.dumps(
            {
                "default_search_provider_data": {
                    "template_url_data": {"url": "https://example.test/default?q={searchTerms}"}
                }
            }
        ),
        encoding="utf-8",
    )
    (other / "Preferences").write_text("{}", encoding="utf-8")
    _write_web_data(other / "Web Data", "{google:baseURL}search?q={searchTerms}")
    found = discover_search_template(tmp_path, "google-chrome.desktop")
    assert found == "https://www.google.com/search?q={searchTerms}"
    assert template_from_web_data(other / "Web Data") == found


def _write_web_data(path: Path, url: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    connection.execute("CREATE TABLE keywords (id INTEGER PRIMARY KEY, url TEXT)")
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('Default Search Provider ID', '3')"
    )
    connection.execute("INSERT INTO keywords (id, url) VALUES (3, ?)", (url,))
    connection.commit()
    connection.close()


def _mozlz4(payload: bytes) -> bytes:
    return b"mozLz40\0" + len(payload).to_bytes(4, "little") + _lz4_literals(payload)


def _lz4_literals(payload: bytes) -> bytes:
    literal = len(payload)
    if literal < 15:
        return bytes([literal << 4]) + payload
    extra = literal - 15
    tail = bytearray()
    while extra >= 255:
        tail.append(255)
        extra -= 255
    tail.append(extra)
    return bytes([15 << 4]) + bytes(tail) + payload

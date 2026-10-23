# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a search URL from the desktop's own search engine.

A Chromium profile stores Google as ``{google:baseURL}``. That token
is expanded to the base Chromium uses. When no browser engine can be
read, the Settings fallback is used. This module does not open a
browser, a socket, or a log.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

_PLACEHOLDER = "{searchTerms}"
_QUERY_MAX = 1500
_CHROMIUM_GOOGLE_BASE = "https://www.google.com/"
FALLBACK_SEARCH_TEMPLATE = "https://duckduckgo.com/?q={searchTerms}"
_OTHER_TOKEN = re.compile(r"\{(?!searchTerms\})[^{}]+\}")
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}$")


def search_target(text: object, template: object) -> str | None:
    """An https URL, or None when the engine or the text cannot be used."""

    if not isinstance(text, str):
        return None
    query = " ".join(text.split())
    if not query:
        return None
    if len(query) > _QUERY_MAX:
        query = query[:_QUERY_MAX]
    prepared = accept_template(template)
    if prepared is None:
        return None
    encoded = quote(query, safe="")
    url = prepared.replace("%s", encoded).replace(_PLACEHOLDER, encoded)
    return url if _https_url(url) else None


def accept_template(value: object) -> str | None:
    """Keep an https template that still has a query placeholder."""

    if not isinstance(value, str):
        return None
    template = value.strip()
    if not template.startswith("https://"):
        return None
    if _PLACEHOLDER not in template and "%s" not in template:
        return None
    if any(char in template for char in ("\n", "\r", " ")):
        return None
    return template if _https_url(template.replace(_PLACEHOLDER, "q").replace("%s", "q")) else None


def discover_search_template(home: Path, desktop_id: str, setting: str | None = None) -> str | None:
    """Read the default browser's saved search template. Unknown means None."""

    chosen = accept_template(setting)
    if chosen is not None:
        return chosen
    ident = desktop_id.casefold() if isinstance(desktop_id, str) else ""
    if "firefox" in ident:
        return _firefox_template(home)
    if "chrome" in ident or "chromium" in ident or "brave" in ident or "edge" in ident:
        return _chromium_template(home, ident)
    return None


def choose_search_template(
    home: Path,
    desktop_id: str,
    setting: str | None = None,
    fallback: str | None = None,
) -> tuple[str | None, str]:
    """The browser template, or the Settings fallback. Nothing is opened."""

    found = discover_search_template(home, desktop_id, setting)
    if found is not None:
        return found, "browser"
    chosen = accept_template(fallback if fallback is not None else FALLBACK_SEARCH_TEMPLATE)
    if chosen is not None:
        return chosen, "fallback"
    return None, "none"


def clamp_search_fallback(value: object) -> str:
    """An https template, or the Settings default when the value is unusable."""

    chosen = accept_template(value)
    return chosen if chosen is not None else FALLBACK_SEARCH_TEMPLATE


def normalize_search_url(value: object) -> str | None:
    """Turn a browser template into an https URL. Other tokens are dropped."""

    if not isinstance(value, str):
        return None
    direct = accept_template(value)
    if direct is not None:
        return direct
    text = value.strip()
    text = text.replace("{google:baseURL}", _CHROMIUM_GOOGLE_BASE)
    text = text.replace("{google:baseSuggestURL}", _CHROMIUM_GOOGLE_BASE)
    text = text.replace("{inputEncoding}", "UTF-8")
    text = _OTHER_TOKEN.sub("", text)
    text = text.replace("?&", "?").replace("&&", "&")
    while "&&" in text:
        text = text.replace("&&", "&")
    if text.endswith("&") or text.endswith("?"):
        text = text[:-1]
    return accept_template(text)


def decode_mozlz4(blob: bytes) -> bytes | None:
    """Unpack a Firefox ``search.json.mozlz4`` blob. None when it is not one."""

    magic = b"mozLz40\0"
    if not isinstance(blob, bytes) or not blob.startswith(magic) or len(blob) < 12:
        return None
    size = int.from_bytes(blob[8:12], "little")
    if size <= 0 or size > 5_000_000:
        return None
    try:
        return _lz4_block(blob[12:], size)
    except (ValueError, IndexError):
        return None


def template_from_firefox(payload: object) -> str | None:
    """The default engine's https template, or None."""

    if not isinstance(payload, dict):
        return None
    engines = payload.get("engines")
    if not isinstance(engines, list):
        return None
    meta = payload.get("metaData")
    default_id = ""
    if isinstance(meta, dict):
        for key in ("defaultEngineId", "appDefaultEngineId"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                default_id = value
                break
    chosen = _firefox_engine(engines, default_id)
    if chosen is None:
        return None
    urls = chosen.get("_urls")
    if not isinstance(urls, list):
        urls = chosen.get("urls")
    if not isinstance(urls, list):
        return None
    for url in urls:
        if not isinstance(url, dict):
            continue
        template = url.get("template")
        if not isinstance(template, str) or not template.startswith("https://"):
            continue
        built = _with_params(template, url.get("params"))
        accepted = accept_template(built)
        if accepted is not None:
            return accepted
    return None


def template_from_chromium(payload: object) -> str | None:
    """A Chromium preferences search URL, when it is already https."""

    if not isinstance(payload, dict):
        return None
    data = payload.get("default_search_provider_data")
    if isinstance(data, dict):
        row = data.get("template_url_data")
        if isinstance(row, dict):
            found = normalize_search_url(row.get("url"))
            if found is not None:
                return found
    legacy = payload.get("default_search_provider")
    if isinstance(legacy, dict):
        for key in ("search_url", "url"):
            found = normalize_search_url(legacy.get(key))
            if found is not None:
                return found
    return None


def template_from_web_data(path: Path) -> str | None:
    """The default engine URL in a Chromium ``Web Data`` database."""

    if not path.is_file():
        return None
    uri = "file:" + quote(str(path), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
    except sqlite3.Error:
        return None
    try:
        meta = connection.execute(
            "SELECT value FROM meta WHERE key = ?",
            ("Default Search Provider ID",),
        ).fetchone()
        if meta is None:
            return None
        try:
            ident = int(meta[0])
        except (TypeError, ValueError):
            return None
        row = connection.execute(
            "SELECT url FROM keywords WHERE id = ?",
            (ident,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if row is None:
        return None
    return normalize_search_url(row[0])


def _firefox_template(home: Path) -> str | None:
    roots = (
        home / ".mozilla" / "firefox",
        home / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox",
    )
    for root in roots:
        profile = _firefox_profile(root)
        if profile is None:
            continue
        blob_path = profile / "search.json.mozlz4"
        if not blob_path.is_file():
            continue
        try:
            raw = decode_mozlz4(blob_path.read_bytes())
            payload = json.loads(raw.decode("utf-8")) if raw is not None else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        found = template_from_firefox(payload)
        if found is not None:
            return found
    return None


def _chromium_template(home: Path, ident: str) -> str | None:
    names: list[Path] = []
    if "brave" in ident:
        names.append(home / ".config" / "BraveSoftware" / "Brave-Browser")
    elif "edge" in ident:
        names.append(home / ".config" / "microsoft-edge")
    elif "chromium" in ident:
        names.append(home / ".config" / "chromium")
        names.append(home / ".var" / "app" / "org.chromium.Chromium" / "config" / "chromium")
    else:
        names.append(home / ".config" / "google-chrome")
        names.append(home / ".var" / "app" / "com.google.Chrome" / "config" / "google-chrome")
    for root in names:
        for profile in _chromium_profiles(root):
            found = _chromium_profile_template(profile)
            if found is not None:
                return found
    return None


def _chromium_profiles(root: Path) -> list[Path]:
    """Last-used profile first, then Default, then any other profile."""

    last = _chromium_last_used(root)
    ordered: list[Path] = []
    if last:
        ordered.append(root / last)
    default = root / "Default"
    if default not in ordered:
        ordered.append(default)
    if not root.is_dir():
        return ordered
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return ordered
    for child in children:
        if child in ordered or not child.is_dir():
            continue
        if (child / "Preferences").is_file() or (child / "Web Data").is_file():
            ordered.append(child)
    return ordered


def _chromium_last_used(root: Path) -> str:
    path = root / "Local State"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    profile = payload.get("profile") if isinstance(payload, dict) else None
    last = profile.get("last_used") if isinstance(profile, dict) else None
    if not isinstance(last, str) or not _PROFILE_NAME.fullmatch(last):
        return ""
    return last


def _chromium_profile_template(profile: Path) -> str | None:
    for name in ("Preferences", "Secure Preferences"):
        path = profile / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        found = template_from_chromium(payload)
        if found is not None:
            return found
    return template_from_web_data(profile / "Web Data")


def _firefox_profile(root: Path) -> Path | None:
    path = root / "profiles.ini"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    sections: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        row = line.strip()
        if row.startswith("[") and row.endswith("]"):
            if current:
                sections.append(current)
            current = {}
            continue
        if "=" not in row:
            continue
        key, value = row.split("=", 1)
        current[key.strip()] = value.strip()
    if current:
        sections.append(current)
    install = next(
        (
            row.get("Default")
            for row in sections
            if "Path" not in row and row.get("Default") not in (None, "", "0", "1")
        ),
        None,
    )
    if isinstance(install, str) and install:
        folder = Path(install)
        return folder if folder.is_absolute() else root / folder
    chosen = next((row for row in sections if row.get("Default") == "1" and row.get("Path")), None)
    if chosen is None:
        chosen = next((row for row in sections if row.get("Path")), None)
    if chosen is None:
        return None
    folder = Path(chosen["Path"])
    if chosen.get("IsRelative", "1") != "0":
        folder = root / folder
    return folder


def _firefox_engine(engines: list[object], default_id: str) -> dict[str, object] | None:
    rows = [row for row in engines if isinstance(row, dict)]
    if default_id:
        for row in rows:
            ident = row.get("id")
            if isinstance(ident, str) and ident == default_id:
                return row
    return None


def _with_params(template: str, params: object) -> str:
    if _PLACEHOLDER in template or "%s" in template:
        return template
    if not isinstance(params, list):
        return template
    parts: list[str] = []
    found = False
    for param in params:
        if not isinstance(param, dict):
            continue
        name = param.get("name")
        value = param.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if value == _PLACEHOLDER:
            found = True
            parts.append(f"{quote(name, safe='')}={_PLACEHOLDER}")
        else:
            parts.append(f"{quote(name, safe='')}={quote(value, safe='')}")
    if not found or not parts:
        return template
    joiner = "&" if "?" in template else "?"
    return template + joiner + "&".join(parts)


def _https_url(value: str) -> bool:
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        return False
    return bool(urlunsplit(parts))


def _lz4_block(data: bytes, size: int) -> bytes:
    out = bytearray()
    index = 0
    length = len(data)
    while index < length and len(out) < size:
        token = data[index]
        index += 1
        literal = token >> 4
        if literal == 15:
            while True:
                extra = data[index]
                index += 1
                literal += extra
                if extra != 255:
                    break
        out += data[index : index + literal]
        index += literal
        if len(out) >= size or index >= length:
            break
        offset = data[index] | (data[index + 1] << 8)
        index += 2
        if offset == 0 or offset > len(out):
            raise ValueError
        match = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while True:
                extra = data[index]
                index += 1
                match += extra
                if extra != 255:
                    break
        start = len(out) - offset
        for _ in range(match):
            if len(out) >= size:
                break
            out.append(out[start])
            start += 1
    if len(out) < size:
        raise ValueError
    return bytes(out[:size])

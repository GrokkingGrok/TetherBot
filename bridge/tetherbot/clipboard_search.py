# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a search URL from the desktop's own search engine.

No search host is chosen here. A missing or unreadable engine returns
None. This module does not open a browser, a socket, or a log.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

_PLACEHOLDER = "{searchTerms}"
_QUERY_MAX = 1500


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
    if not isinstance(data, dict):
        return None
    row = data.get("template_url_data")
    if not isinstance(row, dict):
        return None
    return accept_template(row.get("url"))


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
        path = root / "Default" / "Preferences"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        found = template_from_chromium(payload)
        if found is not None:
            return found
    return None


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

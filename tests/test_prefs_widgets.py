# SPDX-License-Identifier: GPL-2.0-or-later
"""Prefs and window widgets stay on the libadwaita this extension runs against."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "extension" / "prefs.js"
WINDOW = ROOT / "bridge" / "tetherbot" / "window.py"
_CTOR = re.compile(r"new (Adw|Gtk)\.(\w+)\(\{([^{}]*)\}\)", re.S)
_PY_CTOR = re.compile(r"\b(Adw|Gtk)\.(\w+)\(([^)]*)\)", re.S)
_KEY = re.compile(r"(?:^|[(,\n])\s*([A-Za-z_][\w]*)\s*[:=]", re.M)


def _props(cls) -> set[str]:
    return {prop.name.replace("_", "-") for prop in cls.list_properties()}


def _js_properties(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for mod, name, body in _CTOR.findall(text):
        for key in re.findall(r"^\s*([A-Za-z_][\w-]*)\s*:", body, re.M):
            found.append((mod, name, key))
    return found


def _py_properties(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for mod, name, body in _PY_CTOR.findall(text):
        for key in _KEY.findall(body):
            if key in {"self", "lambda", "if", "or", "and", "not"}:
                continue
            found.append((mod, name, key))
    return found


def test_prefs_and_window_widgets_use_known_properties():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk
    except ValueError as exc:
        pytest.skip(str(exc))

    spaces = {"Adw": Adw, "Gtk": Gtk}
    missing: list[str] = []
    pairs = _js_properties(PREFS.read_text(encoding="utf-8"))
    pairs.extend(_py_properties(WINDOW.read_text(encoding="utf-8")))
    assert pairs
    for mod, name, key in pairs:
        cls = getattr(spaces[mod], name, None)
        if cls is None or not hasattr(cls, "list_properties"):
            continue
        if key.replace("_", "-") not in _props(cls):
            missing.append(f"{mod}.{name}.{key}")
    assert missing == []
    entry = Adw.EntryRow(title="Search address", tooltip_text="hint")
    assert "subtitle" not in _props(type(entry))
    note = Adw.ActionRow(title="Search fallback", subtitle="hint")
    assert note.get_subtitle() == "hint"

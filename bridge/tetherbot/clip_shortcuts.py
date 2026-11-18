# SPDX-License-Identifier: GPL-2.0-or-later
"""Clipboard editor keys and tag chips for the window.

The window's Tag and Edit editors sit in the row. These helpers decide
what a key does and how a chip list changes. They do not touch GTK.
"""

from __future__ import annotations

TAG_NAME_MAX = 40
CLIP_TAG_MAX = 8
TAG_LIMIT_LINE = f"A clip keeps up to {CLIP_TAG_MAX} tags."
TAG_NAME_LINE = f"A tag is 1 to {TAG_NAME_MAX} characters."

_TONES = frozenset(
    {"red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"}
)


def clip_editor_key(kind: str, key: str, *, control: bool) -> str:
    """Return what a clipboard editor should do with this key.

    ``kind`` is ``edit`` or ``tag``. ``key`` is ``enter`` or ``escape``.
    The result is ``cancel``, ``save``, ``commit-tag``, ``newline``, or
    an empty string when the editor should leave the key alone.
    """

    if key == "escape" and not control:
        return "cancel"
    if key != "enter":
        return ""
    if control:
        return "save"
    if kind == "tag":
        return "commit-tag"
    if kind == "edit":
        return "newline"
    return ""


def inline_escape(kind: str, pending: str) -> str:
    """Return ``clear`` or ``cancel`` for Escape in an inline editor.

    A tag field that still has text only drops that text. An empty tag
    field, and any Edit, closes and discards what was not saved.
    """

    if kind == "tag" and isinstance(pending, str) and pending.strip():
        return "clear"
    return "cancel"


def normalize_tag_name(raw: object) -> str:
    """Collapse whitespace. Empty, too long, or a control character is empty."""

    if not isinstance(raw, str):
        return ""
    name = " ".join(raw.split())
    if not name or len(name) > TAG_NAME_MAX:
        return ""
    if any(ord(char) < 32 for char in name):
        return ""
    return name


def tag_tone(color: object) -> str:
    return color if isinstance(color, str) and color in _TONES else "gray"


def _key(name: str) -> str:
    return name.casefold()


def _copy(chips: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(chip) for chip in chips]


def selected_count(chips: list[dict[str, object]]) -> int:
    return sum(1 for chip in chips if chip.get("selected") is True)


def tag_chips(
    *,
    clip_tags: object = (),
    other_tags: object = (),
    known: object = (),
) -> list[dict[str, object]]:
    """The clip's own tags first and selected. Other tags follow, unselected."""

    chips: list[dict[str, object]] = []
    index: dict[str, dict[str, object]] = {}

    def add(name: object, color: object, selected: bool) -> None:
        clean = normalize_tag_name(name)
        if not clean:
            return
        found = index.get(_key(clean))
        if found is not None:
            if not found.get("color") and isinstance(color, str) and color:
                found["color"] = color
            return
        chip: dict[str, object] = {
            "name": clean,
            "color": color if isinstance(color, str) else "",
            "selected": selected,
        }
        index[_key(clean)] = chip
        chips.append(chip)

    for tag in clip_tags if isinstance(clip_tags, list) else []:
        if isinstance(tag, dict):
            add(tag.get("name"), tag.get("color"), True)
    rest: list[tuple[object, object]] = []
    for row in known if isinstance(known, list) else []:
        if isinstance(row, dict):
            rest.append((row.get("tag"), row.get("color")))
    for tag in other_tags if isinstance(other_tags, list) else []:
        if isinstance(tag, dict):
            rest.append((tag.get("name"), tag.get("color")))
    rest.sort(key=lambda item: str(item[0]).casefold())
    for name, color in rest:
        add(name, color, False)
    return chips


def toggle_tag_chip(
    chips: list[dict[str, object]], name: str
) -> tuple[list[dict[str, object]], str]:
    next_chips = _copy(chips)
    chip = next((item for item in next_chips if _key(str(item.get("name"))) == _key(name)), None)
    if chip is None:
        return next_chips, ""
    if chip.get("selected") is not True and selected_count(next_chips) >= CLIP_TAG_MAX:
        return next_chips, TAG_LIMIT_LINE
    chip["selected"] = chip.get("selected") is not True
    return next_chips, ""


def add_tag_chip(
    chips: list[dict[str, object]], raw: object
) -> tuple[list[dict[str, object]], str, str]:
    """Return chips, the added name, and an error line.

    A name that is already selected is not added again. The added name is
    empty when nothing changed.
    """

    next_chips = _copy(chips)
    name = normalize_tag_name(raw)
    if not name:
        typed = isinstance(raw, str) and raw.strip() != ""
        return next_chips, "", TAG_NAME_LINE if typed else ""
    found = next(
        (item for item in next_chips if _key(str(item.get("name"))) == _key(name)),
        None,
    )
    if found is not None and found.get("selected") is True:
        return next_chips, str(found.get("name")), ""
    if selected_count(next_chips) >= CLIP_TAG_MAX:
        return next_chips, "", TAG_LIMIT_LINE
    if found is not None:
        found["selected"] = True
        return next_chips, str(found.get("name")), ""
    next_chips.append({"name": name, "color": "", "selected": True})
    return next_chips, name, ""


def selected_tag_payload(chips: list[dict[str, object]]) -> list[dict[str, str]]:
    """The ``SetClipboardTags`` argument. A new tag leaves the color to the bridge."""

    tags: list[dict[str, str]] = []
    for chip in chips:
        if chip.get("selected") is not True:
            continue
        name = chip.get("name")
        if not isinstance(name, str) or not name:
            continue
        tag = {"name": name}
        color = chip.get("color")
        if isinstance(color, str) and color:
            tag["color"] = color
        tags.append(tag)
    return tags

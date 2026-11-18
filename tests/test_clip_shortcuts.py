# SPDX-License-Identifier: GPL-2.0-or-later
"""Window clipboard editor keys and tag chips."""

from tetherbot.clip_shortcuts import (
    add_tag_chip,
    clip_editor_key,
    inline_escape,
    selected_tag_payload,
    tag_chips,
    toggle_tag_chip,
)


def test_edit_enter_is_a_newline_and_ctrl_enter_saves():
    assert clip_editor_key("edit", "enter", control=False) == "newline"
    assert clip_editor_key("edit", "enter", control=True) == "save"


def test_tag_enter_saves_the_typed_tag_and_ctrl_enter_saves():
    assert clip_editor_key("tag", "enter", control=False) == "commit-tag"
    assert clip_editor_key("tag", "enter", control=True) == "save"


def test_escape_cancels_both_editors():
    assert clip_editor_key("edit", "escape", control=False) == "cancel"
    assert clip_editor_key("tag", "escape", control=False) == "cancel"
    assert clip_editor_key("edit", "escape", control=True) == ""


def test_other_keys_are_left_alone():
    assert clip_editor_key("edit", "f", control=True) == ""
    assert clip_editor_key("tag", "a", control=False) == ""


def test_tag_escape_clears_pending_text_and_closes_when_empty():
    assert inline_escape("tag", "later") == "clear"
    assert inline_escape("tag", "   ") == "cancel"
    assert inline_escape("edit", "a line") == "cancel"


def test_tag_chips_select_the_clip_and_offer_the_others():
    chips = tag_chips(
        clip_tags=[{"name": "Now", "color": "blue"}],
        other_tags=[{"name": "Later", "color": "red"}],
        known=[{"tag": "Soon", "color": "green"}],
    )
    assert [chip["name"] for chip in chips] == ["Now", "Later", "Soon"]
    assert chips[0]["selected"] is True
    assert chips[1]["selected"] is False


def test_enter_adds_a_tag_and_a_second_enter_does_not_duplicate_it():
    chips, added, error = add_tag_chip([], "  Later  ")
    assert added == "Later"
    assert error == ""
    again, added, error = add_tag_chip(chips, "later")
    assert added == "Later"
    assert error == ""
    assert selected_tag_payload(again) == [{"name": "Later"}]


def test_toggle_stops_at_eight_tags():
    chips = [
        {"name": f"t{index}", "color": "", "selected": True} for index in range(8)
    ]
    chips.append({"name": "extra", "color": "gray", "selected": False})
    updated, error = toggle_tag_chip(chips, "extra")
    assert error == "A clip keeps up to 8 tags."
    assert updated[-1]["selected"] is False

# SPDX-License-Identifier: GPL-2.0-or-later
"""Window clipboard editor keys and which popover closes save."""

from tetherbot.clip_shortcuts import clip_close_saves, clip_editor_key


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


def test_only_an_unclicked_close_saves():
    assert clip_close_saves(cancelled=False, clicked_in_window=False) is True
    assert clip_close_saves(cancelled=True, clicked_in_window=False) is False
    assert clip_close_saves(cancelled=False, clicked_in_window=True) is False
    assert clip_close_saves(cancelled=True, clicked_in_window=True) is False

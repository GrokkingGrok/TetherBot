# SPDX-License-Identifier: GPL-2.0-or-later
"""Key and close decisions for the window's clipboard editors.

The popover is its own surface. Keys typed into it never reach the window,
and switching to another app dismisses that surface without clearing
``Gtk.Window.is-active``. These two functions are the decisions the window
applies. They do not touch GTK.
"""

from __future__ import annotations


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


def clip_close_saves(*, cancelled: bool, clicked_in_window: bool) -> bool:
    """True when a popover close should keep the edit.

    Escape, Cancel, and a click inside this window discard. A close with
    neither of those, which is what switching to another app does, saves.
    """

    return not cancelled and not clicked_in_window

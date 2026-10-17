# SPDX-License-Identifier: GPL-2.0-or-later
"""Generic seam for an older single-repo todo sync.

A concrete legacy inbox format stays out of this public repository.
This module does not define a field map. It is off until enabled.
See docs/SPEC.md section 11.

When a sink outside this repo implements the seam:

- An unknown inbox schema fails closed and leaves the todo file untouched.
- Live mode refuses to run while the previous sync unit is still active.
- The sink writes only the paths it owns.
"""


class LegacyTodoSink:
    name = "legacy-todo"

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx

    def stop(self) -> None:
        self._ctx = None

    def on_items(self, snapshot: object, diff: object) -> None:
        del snapshot, diff
        raise NotImplementedError("legacy-todo is an example sink and is not implemented")

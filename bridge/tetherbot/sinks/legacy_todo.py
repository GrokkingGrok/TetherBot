# SPDX-License-Identifier: GPL-2.0-or-later
"""Example module: legacy single-repo todo sync.

This sink is a placeholder for replacing an older todo sync that already
reads one private repo and writes a local todo file. It is off until
enabled. See docs/SPEC.md section 11.

When it is implemented:

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

# SPDX-License-Identifier: GPL-2.0-or-later
"""Key dialog owned by the bridge.

The prefs window calls ``RequestSecretEntry``. The bridge starts this
process. The fields start empty. A stored key is never read back onto
the screen. The process writes libsecret and exits.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tetherbot.secrets import SecretError, SecretStore, SecretValueError

_SLOT = re.compile(r"^[a-z0-9-]{1,64}$")
_GITHUB = "github-token"


def launch_secret_dialog(slot: str) -> bool:
    """Start the dialog process. False when it cannot start.

    The secret is not an argument. No display means the dialog does not open.
    """

    if not isinstance(slot, str) or _SLOT.fullmatch(slot) is None:
        return False
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return False
    try:
        subprocess.Popen(
            [sys.executable, "-m", "tetherbot.secret_dialog", slot],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def save_slot(store: SecretStore, slot: str, url: str, secret: str) -> None:
    """Write one slot. The return value is empty on purpose."""

    if slot == _GITHUB:
        store.put_github_token(slot, secret)
        return
    store.put_webhook(slot, url, secret)


def retry_stored_slot(slot: str, config_path: Path | None = None) -> None:
    """Ask a running bridge to send parked actions for this slot.

    A failure here does not undo the stored key. The secret is not read.
    """

    try:
        from tetherbot.ctl import _resume_live
        from tetherbot.daemon import default_config_path

        path = default_config_path() if config_path is None else config_path
        _resume_live(path)(slot)
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or _SLOT.fullmatch(args[0]) is None:
        print("tetherbot: the key dialog needs a slot name", file=sys.stderr)
        return 2
    try:
        import gi

        gi.require_version("Adw", "1")
        gi.require_version("Gtk", "4.0")
        from gi.repository import Adw, Gio, Gtk
    except (ImportError, ValueError):
        print(
            "tetherbot: GTK4 and libadwaita are required for the key dialog.",
            file=sys.stderr,
        )
        return 1
    app = _KeyApp(args[0], Adw=Adw, Gtk=Gtk, Gio=Gio)
    return int(app.run([sys.argv[0]]))


class _KeyApp:
    """A short-lived window. Constructed only after GTK imports succeed."""

    def __init__(self, slot: str, *, Adw: object, Gtk: object, Gio: object) -> None:
        self._slot = slot
        self._Adw = Adw
        self._Gtk = Gtk
        self._error = Gtk.Label(label="", wrap=True)
        self._error.add_css_class("error")
        self._error.set_visible(False)
        flags = Gio.ApplicationFlags.NON_UNIQUE
        self._app = Adw.Application(
            application_id="io.github.grokkinggrok.TetherBot.Keys",
            flags=flags,
        )
        self._app.connect("activate", self._activate)

    def run(self, args: list[str]) -> int:
        return int(self._app.run(args))

    def _activate(self, app: object) -> None:
        Adw = self._Adw
        Gtk = self._Gtk
        github = self._slot == _GITHUB
        title = "GitHub token" if github else "Webhook keys"
        window = Adw.ApplicationWindow(application=app, title=title)
        window.set_default_size(420, 280)
        toolbar = Adw.HeaderBar()
        page = Adw.PreferencesPage()
        hint = "Paste the token. A token that is already stored is not shown."
        if not github:
            hint = (
                "In the bot: Details, Routines, the routine, Webhook. "
                "Paste the POST URL and the key. A stored key is not shown."
            )
        group = Adw.PreferencesGroup(title=title, description=hint)
        self._url = Gtk.Entry()
        if not github:
            url_row = Adw.ActionRow(title="Webhook URL")
            self._url.set_hexpand(True)
            self._url.set_input_purpose(Gtk.InputPurpose.URL)
            url_row.add_suffix(self._url)
            group.add(url_row)
        self._secret = Gtk.PasswordEntry(show_peek_icon=True)
        self._secret.set_hexpand(True)
        secret_row = Adw.ActionRow(title="Token" if github else "Webhook key")
        secret_row.add_suffix(self._secret)
        group.add(secret_row)
        group.add(self._error)
        page.add(group)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda _button: self._save(window))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: window.close())
        toolbar.pack_start(cancel)
        toolbar.pack_end(save)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(toolbar)
        box.append(page)
        window.set_content(box)
        window.present()

    def _save(self, window: object) -> None:
        from tetherbot.secrets import open_secret_store

        url = "" if self._slot == _GITHUB else self._url.get_text().strip()
        secret = self._secret.get_text()
        store = open_secret_store()
        try:
            save_slot(store, self._slot, url, secret)
        except SecretValueError as exc:
            self._show_error(str(exc))
            return
        except SecretError as exc:
            self._show_error(str(exc))
            return
        retry_stored_slot(self._slot)
        window.close()

    def _show_error(self, message: str) -> None:
        self._error.set_label(message)
        self._error.set_visible(True)


if __name__ == "__main__":
    raise SystemExit(main())

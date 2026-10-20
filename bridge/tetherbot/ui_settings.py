# SPDX-License-Identifier: GPL-2.0-or-later
"""UI settings from the extension schema.

Poll interval, undo length, muted bots, and hidden bots live in gsettings.
Secrets do not. This module does not import PyGObject until a compiled
schema is present, and it never reads a secret.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

POLL_DEFAULT = 120
POLL_MIN = 60
POLL_MAX = 900
UNDO_DEFAULT = 5
UNDO_MIN = 2
UNDO_MAX = 30

SCHEMA_ID = "org.gnome.shell.extensions.tetherbot"
EXTENSION_UUID = "tetherbot@grokkinggrok.github.io"
_BOT = re.compile(r"^[a-z0-9-]{1,64}$")


@dataclass(frozen=True)
class UiSettings:
    """One snapshot of the UI settings. Defaults match the schema."""

    poll_seconds: int = POLL_DEFAULT
    poll_set: bool = False
    undo_seconds: int = UNDO_DEFAULT
    muted_bots: frozenset[str] = frozenset()
    hidden_bots: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_seconds", clamp_poll_seconds(self.poll_seconds))
        object.__setattr__(self, "undo_seconds", clamp_undo_seconds(self.undo_seconds))
        object.__setattr__(self, "muted_bots", bot_set(self.muted_bots))
        object.__setattr__(self, "hidden_bots", bot_set(self.hidden_bots))


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def clamp_poll_seconds(value: object) -> int:
    """Keep a poll interval inside 60 to 900 seconds.

    A non-positive value is unset and becomes 120, not the minimum.
    """

    if not _positive_int(value):
        return POLL_DEFAULT
    return min(POLL_MAX, max(POLL_MIN, int(value)))


def clamp_undo_seconds(value: object) -> int:
    """Keep an undo window inside 2 to 30 seconds.

    A non-positive value is unset and becomes 5, not the minimum.
    """

    if not _positive_int(value):
        return UNDO_DEFAULT
    return min(UNDO_MAX, max(UNDO_MIN, int(value)))


def effective_poll_seconds(stored: object, config: object) -> int:
    """A saved positive interval, else config.toml, else 120. Never 0."""

    if _positive_int(stored):
        return clamp_poll_seconds(stored)
    if _positive_int(config):
        return clamp_poll_seconds(config)
    return POLL_DEFAULT


def effective_undo_seconds(stored: object) -> int:
    """A saved positive undo length, else 5. Never 0."""

    if _positive_int(stored):
        return clamp_undo_seconds(stored)
    return UNDO_DEFAULT


def bot_set(values: object) -> frozenset[str]:
    """Bot ids only. Other entries are dropped."""

    if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(value for value in values if isinstance(value, str) and _BOT.fullmatch(value))


def extension_schema_dir() -> Path | None:
    """The installed extension schema directory, when it has been compiled."""

    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    path = base / "gnome-shell" / "extensions" / EXTENSION_UUID / "schemas"
    if (path / "gschemas.compiled").is_file() and any(path.glob("*.gschema.xml")):
        return path
    return None


def load_ui_settings(schema_dir: Path | None = None) -> UiSettings:
    """Read the compiled schema. Missing schema means the defaults."""

    directory = extension_schema_dir() if schema_dir is None else schema_dir
    if directory is None:
        return UiSettings()
    try:
        settings = _gio_settings(directory)
    except Exception:
        return UiSettings()
    if settings is None:
        return UiSettings()
    poll_user = _user_int(settings, "poll-seconds")
    undo_user = _user_int(settings, "undo-seconds")
    return UiSettings(
        poll_seconds=poll_user if poll_user is not None else POLL_DEFAULT,
        poll_set=poll_user is not None,
        undo_seconds=undo_user if undo_user is not None else UNDO_DEFAULT,
        muted_bots=bot_set(list(settings.get_strv("muted-bots"))),
        hidden_bots=bot_set(list(settings.get_strv("hidden-bots"))),
    )


def resolve_ui_settings(owner: object | None) -> UiSettings:
    """A pinned snapshot on ``owner``, or a live read of the schema."""

    if owner is not None:
        pinned = getattr(owner, "ui_settings", None)
        if isinstance(pinned, UiSettings):
            return pinned
    return load_ui_settings()


def notice_bot(item_json: str) -> str:
    """The bot id on a notification payload. Empty when it is not named."""

    try:
        payload = json.loads(item_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    bot = payload.get("bot")
    if isinstance(bot, str) and _BOT.fullmatch(bot):
        return bot
    source = payload.get("source")
    if isinstance(source, dict):
        named = source.get("bot")
        if isinstance(named, str) and _BOT.fullmatch(named):
            return named
    return ""


def _user_int(settings: object, key: str) -> int | None:
    """A positive user-set integer. The schema default and 0 are unset."""

    variant = settings.get_user_value(key)
    if variant is None:
        return None
    try:
        value = variant.unpack()
    except Exception:
        return None
    if not _positive_int(value):
        return None
    return int(value)


def _gio_settings(directory: Path) -> object | None:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.new_from_directory(str(directory), None, True)
    schema = source.lookup(SCHEMA_ID, False)
    if schema is None:
        return None
    return Gio.Settings.new_full(schema, None, None)

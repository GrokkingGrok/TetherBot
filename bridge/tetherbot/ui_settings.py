# SPDX-License-Identifier: GPL-2.0-or-later
"""UI settings from the extension schema.

Poll interval, undo length, muted bots, hidden bots, and completed-todo
history live in gsettings. Secrets do not. This module does not import
PyGObject until a compiled schema is present, and it never reads a secret.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

POLL_DEFAULT = 120
POLL_MIN = 60
POLL_MAX = 900
UNDO_DEFAULT = 5
UNDO_MIN = 2
UNDO_MAX = 30
DAY_SECONDS = 86400
YEAR_SECONDS = 365 * DAY_SECONDS
HISTORY_AMOUNT_DEFAULT = 1
HISTORY_AMOUNT_MIN = 1
HISTORY_AMOUNT_MAX = 999
HISTORY_UNIT_DEFAULT = "years"
HISTORY_UNITS = ("hours", "days", "weeks", "months", "years")
HISTORY_MAX_SECONDS = HISTORY_AMOUNT_MAX * YEAR_SECONDS
_HISTORY_KEYS = frozenset({"history-enabled", "history-amount", "history-unit"})
_HISTORY_SCALE = {
    "hours": 3600,
    "days": DAY_SECONDS,
    "weeks": 7 * DAY_SECONDS,
    "months": 30 * DAY_SECONDS,
    "years": YEAR_SECONDS,
}

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
    history_enabled: bool = True
    history_amount: int = HISTORY_AMOUNT_DEFAULT
    history_unit: str = HISTORY_UNIT_DEFAULT

    def __post_init__(self) -> None:
        object.__setattr__(self, "poll_seconds", clamp_poll_seconds(self.poll_seconds))
        object.__setattr__(self, "undo_seconds", clamp_undo_seconds(self.undo_seconds))
        object.__setattr__(self, "muted_bots", bot_set(self.muted_bots))
        object.__setattr__(self, "hidden_bots", bot_set(self.hidden_bots))
        object.__setattr__(self, "history_enabled", self.history_enabled is True)
        object.__setattr__(self, "history_amount", clamp_history_amount(self.history_amount))
        object.__setattr__(self, "history_unit", clamp_history_unit(self.history_unit))

    @property
    def done_history_seconds(self) -> int | None:
        """Seconds of completed-todo history, or none when history is off."""

        return history_seconds(self.history_enabled, self.history_amount, self.history_unit)


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


def clamp_history_amount(value: object) -> int:
    """Keep a history amount inside 1 to 999. A non-positive value is 1."""

    if not _positive_int(value):
        return HISTORY_AMOUNT_DEFAULT
    return min(HISTORY_AMOUNT_MAX, max(HISTORY_AMOUNT_MIN, int(value)))


def clamp_history_unit(value: object) -> str:
    """A known unit, or years."""

    if isinstance(value, str) and value in HISTORY_UNITS:
        return value
    return HISTORY_UNIT_DEFAULT


def history_seconds(enabled: object, amount: object, unit: object) -> int | None:
    """The Show done window in seconds. None when history is off.

    A month is 30 days and a year is 365 days. The window does not follow
    the calendar, so the same setting hides the same todos everywhere.
    """

    if enabled is not True:
        return None
    scale = _HISTORY_SCALE[clamp_history_unit(unit)]
    return clamp_history_amount(amount) * scale


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
        history_enabled=_schema_bool(settings, "history-enabled", True),
        history_amount=_schema_int(settings, "history-amount", HISTORY_AMOUNT_DEFAULT),
        history_unit=_schema_choice(
            settings,
            "history-unit",
            HISTORY_UNIT_DEFAULT,
            HISTORY_UNITS,
        ),
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


def watch_history_settings(callback: Callable[[], None]) -> object | None:
    """Reload when the completed-todo history keys change.

    The returned settings object must be kept. A missing schema, or a
    schema from before these keys existed, does not watch.
    """

    directory = extension_schema_dir()
    if directory is None:
        return None
    try:
        settings = _gio_settings(directory)
    except Exception:
        return None
    if settings is None or not all(_schema_has(settings, key) for key in _HISTORY_KEYS):
        return None

    def _changed(_settings: object, key: str) -> None:
        if key in _HISTORY_KEYS:
            callback()

    settings.connect("changed", _changed)
    return settings


def _schema_has(settings: object, key: str) -> bool:
    try:
        schema = settings.get_property("settings-schema")
    except Exception:
        return False
    if schema is None:
        return False
    try:
        return bool(schema.has_key(key))
    except Exception:
        return False


def _schema_bool(settings: object, key: str, default: bool) -> bool:
    if not _schema_has(settings, key):
        return default
    try:
        return bool(settings.get_boolean(key))
    except Exception:
        return default


def _schema_int(settings: object, key: str, default: int) -> int:
    if not _schema_has(settings, key):
        return default
    try:
        value = settings.get_int(key)
    except Exception:
        return default
    if not _positive_int(value):
        return default
    return int(value)


def _schema_choice(
    settings: object,
    key: str,
    default: str,
    choices: tuple[str, ...],
) -> str:
    if not _schema_has(settings, key):
        return default
    try:
        value = settings.get_string(key)
    except Exception:
        return default
    if isinstance(value, str) and value in choices:
        return value
    return default


def _gio_settings(directory: Path) -> object | None:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.new_from_directory(str(directory), None, True)
    schema = source.lookup(SCHEMA_ID, False)
    if schema is None:
        return None
    return Gio.Settings.new_full(schema, None, None)

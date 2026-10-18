#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Look for a stored TetherBot secret without printing it.

Reads the github token and each configured webhook from libsecret, then
searches config, state, cache, the clone, ``dconf dump /``, and
``journalctl --user``. A match prints the category name only.

Exit 0 when every scanned place is clean, 1 when something matched, 2 when
there is nothing to scan or a required command is missing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "bridge"))

from tetherbot.sweep import report, scan  # noqa: E402

_MIN_LENGTH = 12


def main() -> int:
    values = _load_values()
    if values is None:
        return 2
    if not values:
        print("no secret is stored; nothing to scan", file=sys.stderr)
        return 2
    short = any(len(value) < _MIN_LENGTH for value in values)
    if short:
        print("a stored value is too short to scan safely", file=sys.stderr)
        return 2
    data = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
    config = _xdg("XDG_CONFIG_HOME", Path.home() / ".config")
    state = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")
    cache = _xdg("XDG_CACHE_HOME", Path.home() / ".cache")
    roots = {
        "config": config / "tetherbot",
        "state": state / "tetherbot",
        "cache": cache / "tetherbot",
        "clone": data / "tetherbot" / "repos",
    }
    unit = config / "systemd" / "user" / "tetherbot.service"
    dbus = data / "dbus-1" / "services" / "io.github.grokkinggrok.TetherBot1.service"
    extra = [path for path in (unit, dbus) if path.is_file()]
    skipped: list[str] = []
    journal, journal_ok = _capture(["journalctl", "--user", "--no-pager", "-o", "cat"])
    if not journal_ok:
        skipped.append("journal")
        journal = ""
    dconf, dconf_ok = _capture(["dconf", "dump", "/"])
    if not dconf_ok:
        skipped.append("dconf")
        dconf = ""
    hits = scan(values, roots, journal=journal, dconf=dconf)
    for path in extra:
        if any(value.encode("utf-8") in path.read_bytes() for value in values):
            label = "unit" if path == unit else "dbus"
            if label not in hits:
                hits.append(label)
    text = report(hits, skipped)
    sys.stdout.write(text)
    if hits:
        return 1
    if skipped:
        return 2
    return 0


def _load_values() -> list[str] | None:
    """Return secret strings, or None when lookup itself failed."""

    found: list[str] = []
    token = _lookup("github-token", "github-token")
    if token is None:
        return None
    if token:
        found.append(token)
    for slot in _webhook_slots():
        raw = _lookup("webhook", slot)
        if raw is None:
            return None
        if not raw:
            continue
        found.append(raw)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            for key in ("url", "key"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    found.append(value)
    unique: list[str] = []
    for value in found:
        if value not in unique:
            unique.append(value)
    return unique


def _webhook_slots() -> list[str]:
    path = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "tetherbot" / "config.toml"
    if not path.is_file():
        return []
    try:
        import tomllib
    except ImportError:
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    bots = raw.get("bots") if isinstance(raw, dict) else None
    if not isinstance(bots, dict):
        return []
    slots: list[str] = []
    for table in bots.values():
        if not isinstance(table, dict):
            continue
        slot = table.get("webhook_slot")
        if isinstance(slot, str) and slot and slot not in slots:
            slots.append(slot)
    return slots


def _lookup(kind: str, slot: str) -> str | None:
    """Return the secret, ``""`` when it is absent, or None on failure."""

    if _have("secret-tool"):
        completed = subprocess.run(
            ["secret-tool", "lookup", "kind", kind, "slot", slot],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode == 0:
            return completed.stdout
        if completed.returncode == 1:
            return ""
        print(f"secret-tool could not read {kind}", file=sys.stderr)
        return None
    return _lookup_libsecret(kind, slot)


def _lookup_libsecret(kind: str, slot: str) -> str | None:
    try:
        from tetherbot.secrets import SecretLocked, open_secret_store
    except Exception:
        print("secret service is not available", file=sys.stderr)
        return None
    store = open_secret_store()
    try:
        if kind == "github-token":
            token = store.get_github_token(slot)
            return token or ""
        webhook = store.get_webhook(slot)
    except SecretLocked:
        print("keyring locked", file=sys.stderr)
        return None
    except Exception:
        print("secret service is not available", file=sys.stderr)
        return None
    if webhook is None:
        return ""
    return json.dumps(
        {"key": webhook.key, "url": webhook.url},
        sort_keys=True,
        separators=(",", ":"),
    )


def _capture(command: list[str]) -> tuple[str, bool]:
    if not _have(command[0]):
        print(f"skipped: {command[0]} is not installed", file=sys.stderr)
        return "", False
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(f"skipped: {command[0]} failed", file=sys.stderr)
        return "", False
    if completed.returncode != 0:
        print(f"skipped: {command[0]} failed", file=sys.stderr)
        return "", False
    return completed.stdout, True


def _have(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def _xdg(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else fallback


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop secret service.

Schema ``io.github.grokkinggrok.TetherBot.Secret``. Webhook items store a
JSON blob ``{url, key}``. A github token stores the token alone. Attributes
are ``kind`` and ``slot``. There is no plain-file fallback. Importing this
module does not import PyGObject, and nothing here writes a file.
"""

from __future__ import annotations

import json
import re
from typing import Protocol
from urllib.parse import urlsplit

from tetherbot.log import note_secrets

SCHEMA_NAME = "io.github.grokkinggrok.TetherBot.Secret"
KINDS = ("webhook", "github-token")
_SLOT = re.compile(r"^[a-z0-9-]{1,64}$")


class SecretError(Exception):
    """A secret-service failure. The message does not contain a secret."""


class SecretLocked(SecretError):
    """The keyring is locked or has no collection."""


class SecretUnavailable(SecretError):
    """The secret service cannot be used."""


class SecretValueError(SecretError):
    """The caller passed a value that must not be stored."""


class WebhookSecret:
    def __init__(self, url: str, key: str) -> None:
        self.url = url
        self.key = key


class SecretBackend(Protocol):
    def status(self) -> str:
        """``available``, ``locked``, or ``missing``."""

    def store(self, kind: str, slot: str, label: str, secret: str) -> None:
        """Replace the item for ``kind`` and ``slot``."""

    def lookup(self, kind: str, slot: str) -> str | None:
        """Return the stored secret, or None when the item is absent."""

    def clear(self, kind: str, slot: str) -> bool:
        """Delete the item. Return true when an item was removed."""


class SecretStore:
    """Validate slots and payloads, then delegate to a backend."""

    def __init__(self, backend: SecretBackend) -> None:
        self._backend = backend

    def status(self) -> str:
        return self._backend.status()

    def put_webhook(self, slot: str, url: str, key: str) -> None:
        _check_slot(slot)
        _check_webhook(url, key)
        self._require_available()
        label = f"tetherbot: {slot} webhook"
        blob = json.dumps({"key": key, "url": url}, sort_keys=True, separators=(",", ":"))
        self._backend.store("webhook", slot, label, blob)
        note_secrets((url, key, blob))

    def put_github_token(self, slot: str, token: str) -> None:
        _check_slot(slot)
        if not isinstance(token, str) or not token:
            raise SecretValueError("github token is empty")
        self._require_available()
        self._backend.store("github-token", slot, f"tetherbot: {slot} github token", token)
        note_secrets((token,))

    def get_webhook(self, slot: str) -> WebhookSecret | None:
        _check_slot(slot)
        self._require_available()
        raw = self._backend.lookup("webhook", slot)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            url = payload["url"]
            key = payload["key"]
            if not isinstance(url, str) or not isinstance(key, str):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SecretError("webhook secret is unreadable") from exc
        note_secrets((url, key, raw))
        return WebhookSecret(url, key)

    def get_github_token(self, slot: str) -> str | None:
        _check_slot(slot)
        self._require_available()
        token = self._backend.lookup("github-token", slot)
        if token:
            note_secrets((token,))
        return token

    def forget(self, slot: str) -> bool:
        """Delete every kind stored for ``slot``. True when one was removed."""

        _check_slot(slot)
        self._require_available()
        removed = False
        for kind in KINDS:
            removed = self._backend.clear(kind, slot) or removed
        return removed

    def _require_available(self) -> None:
        status = self.status()
        if status == "locked":
            raise SecretLocked("keyring locked")
        if status != "available":
            raise SecretUnavailable("secret service is not available")


class MemoryBackend:
    """In-memory backend for tests. It has no path and writes no file."""

    def __init__(self, *, status: str = "available") -> None:
        self._status = status
        self.items: dict[tuple[str, str], str] = {}

    def status(self) -> str:
        return self._status

    def store(self, kind: str, slot: str, label: str, secret: str) -> None:
        del label
        self.items[(kind, slot)] = secret

    def lookup(self, kind: str, slot: str) -> str | None:
        return self.items.get((kind, slot))

    def clear(self, kind: str, slot: str) -> bool:
        return self.items.pop((kind, slot), None) is not None


class UnavailableBackend:
    def status(self) -> str:
        return "missing"

    def store(self, kind: str, slot: str, label: str, secret: str) -> None:
        del kind, slot, label, secret
        raise SecretUnavailable("secret service is not available")

    def lookup(self, kind: str, slot: str) -> str | None:
        del kind, slot
        raise SecretUnavailable("secret service is not available")

    def clear(self, kind: str, slot: str) -> bool:
        del kind, slot
        raise SecretUnavailable("secret service is not available")


class LibsecretBackend:
    """libsecret backend. The schema is built lazily and no file is written."""

    def __init__(self) -> None:
        self._schema = build_schema()

    def status(self) -> str:
        secret, service = _secret_service()
        if service is None:
            return "missing"
        try:
            service.load_collections_sync(None)
            collections = service.get_collections() or []
        except Exception:
            return "missing"
        del secret
        if not collections:
            return "missing"
        if all(bool(collection.get_locked()) for collection in collections):
            return "locked"
        return "available"

    def store(self, kind: str, slot: str, label: str, secret: str) -> None:
        module = _secret_module()
        try:
            stored = module.password_store_sync(
                self._schema,
                {"kind": kind, "slot": slot},
                module.COLLECTION_DEFAULT,
                label,
                secret,
                None,
            )
        except Exception as exc:
            raise _from_service(exc) from exc
        if not stored:
            raise SecretLocked("keyring locked")

    def lookup(self, kind: str, slot: str) -> str | None:
        module = _secret_module()
        try:
            value = module.password_lookup_sync(
                self._schema,
                {"kind": kind, "slot": slot},
                None,
            )
        except Exception as exc:
            raise _from_service(exc) from exc
        if not value:
            return None
        return str(value)

    def clear(self, kind: str, slot: str) -> bool:
        module = _secret_module()
        try:
            return bool(
                module.password_clear_sync(
                    self._schema,
                    {"kind": kind, "slot": slot},
                    None,
                )
            )
        except Exception as exc:
            raise _from_service(exc) from exc


def open_secret_store() -> SecretStore:
    """Open libsecret, or a store that reports missing when the typelib is absent."""

    try:
        return SecretStore(LibsecretBackend())
    except SecretUnavailable:
        return SecretStore(UnavailableBackend())


def build_schema() -> object:
    """Build the libsecret schema. Raises ``SecretUnavailable`` when it cannot."""

    module = _secret_module()
    return module.Schema.new(
        SCHEMA_NAME,
        module.SchemaFlags.NONE,
        {
            "kind": module.SchemaAttributeType.STRING,
            "slot": module.SchemaAttributeType.STRING,
        },
    )


def _secret_module() -> object:
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret
    except (ImportError, ValueError) as exc:
        raise SecretUnavailable("secret service is not available") from exc
    return Secret


def _secret_service() -> tuple[object, object | None]:
    module = _secret_module()
    try:
        service = module.Service.get_sync(module.ServiceFlags.NONE, None)
    except Exception:
        return module, None
    return module, service


def _from_service(exc: Exception) -> SecretError:
    del exc
    return SecretLocked("keyring locked")


def _check_slot(slot: str) -> None:
    if not isinstance(slot, str) or _SLOT.fullmatch(slot) is None:
        raise SecretValueError("slot must match [a-z0-9-]{1,64}")


def _check_webhook(url: str, key: str) -> None:
    if not isinstance(url, str) or not isinstance(key, str) or not key:
        raise SecretValueError("webhook url and key are required")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        raise SecretValueError("webhook url must be https without credentials")

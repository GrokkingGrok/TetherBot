# SPDX-License-Identifier: GPL-2.0-or-later
"""Secret store: memory backend, no plain file, and the libsecret schema."""

import logging
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from tetherbot.log import configure_logging
from tetherbot.secrets import (
    SCHEMA_NAME,
    LibsecretBackend,
    MemoryBackend,
    SecretLocked,
    SecretStore,
    SecretUnavailable,
    SecretValueError,
    UnavailableBackend,
    _locked_value,
    _login_collection,
    build_schema,
    keyring_availability,
    open_secret_store,
)

ROOT = Path(__file__).resolve().parents[1]
WEBHOOK_URL = "https://example.test/hook/primary"
WEBHOOK_KEY = "desk-hook-key"


def test_webhook_and_token_round_trip_without_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    store = SecretStore(MemoryBackend())
    store.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    store.put_github_token("github-token", "ghp_abcdefghijklmnopqrstuvwxyz")
    webhook = store.get_webhook("primary-actions")
    assert webhook is not None
    assert webhook.url == WEBHOOK_URL
    assert webhook.key == WEBHOOK_KEY
    assert store.get_github_token("github-token") == "ghp_abcdefghijklmnopqrstuvwxyz"
    assert store.forget("primary-actions") is True
    assert store.get_webhook("primary-actions") is None
    assert store.get_github_token("github-token") == "ghp_abcdefghijklmnopqrstuvwxyz"
    assert store.forget("github-token") is True
    assert store.forget("github-token") is False
    assert list(tmp_path.iterdir()) == []


def test_locked_store_does_not_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    store = SecretStore(MemoryBackend(status="locked"))
    with pytest.raises(SecretLocked, match="keyring locked"):
        store.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    with pytest.raises(SecretLocked, match="keyring locked"):
        store.forget("primary-actions")
    assert list(tmp_path.iterdir()) == []


def test_missing_store_has_no_file_fallback(tmp_path: Path):
    store = SecretStore(UnavailableBackend())
    with pytest.raises(SecretUnavailable, match="not available"):
        store.put_github_token("github-token", "token-value")
    assert list(tmp_path.iterdir()) == []


def test_webhook_url_must_be_https_without_credentials():
    store = SecretStore(MemoryBackend())
    with pytest.raises(SecretValueError, match="https"):
        store.put_webhook("primary-actions", "http://example.test/hook", WEBHOOK_KEY)
    with pytest.raises(SecretValueError, match="https"):
        store.put_webhook("primary-actions", "https://user:pw@example.test/hook", WEBHOOK_KEY)
    assert store.get_webhook("primary-actions") is None


def test_exact_secret_is_masked_in_the_log(tmp_path: Path):
    stream = StringIO()
    logger = logging.getLogger("tetherbot")
    previous = logger.propagate
    try:
        configure_logging(stream=stream, path=tmp_path / "bridge.log")
        store = SecretStore(MemoryBackend())
        store.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
        logger.info("url %s key %s", WEBHOOK_URL, WEBHOOK_KEY)
        text = stream.getvalue() + (tmp_path / "bridge.log").read_text(encoding="utf-8")
        assert WEBHOOK_URL not in text
        assert WEBHOOK_KEY not in text
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = previous


def test_dbus_forget_uses_the_store(tmp_path: Path):
    from tetherbot.daemon import BridgeDaemon
    from tetherbot.service import ServiceError

    store = SecretStore(MemoryBackend())
    store.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
        secrets=store,
    )
    daemon.start()
    assert daemon.api is not None
    daemon.api.call("ForgetSecret", ("primary-actions",))
    assert store.get_webhook("primary-actions") is None
    assert daemon.api.call("RequestSecretEntry", ("primary-actions",)) == (False,)
    with pytest.raises(ServiceError, match="keyring locked"):
        daemon.secrets = SecretStore(MemoryBackend(status="locked"))
        daemon.api.call("ForgetSecret", ("primary-actions",))


def test_schema_builds_when_the_typelib_is_installed():
    try:
        schema = build_schema()
    except SecretUnavailable:
        pytest.skip("Secret-1 typelib is not installed")
    assert schema.name == SCHEMA_NAME
    assert isinstance(LibsecretBackend(), LibsecretBackend)


def test_open_store_does_not_create_a_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    try:
        store = open_secret_store()
    except SecretUnavailable:
        pytest.skip("Secret-1 typelib is not installed")
    assert store.status() in {"available", "locked", "missing"}
    assert list(tmp_path.iterdir()) == []


def test_login_collection_lock_wins_over_an_unlocked_session_collection():
    assert keyring_availability(default_locked=True, collection_locks=[True, False]) == "locked"
    assert keyring_availability(default_locked=False, collection_locks=[True]) == "available"
    assert keyring_availability(default_locked=None, collection_locks=[]) == "missing"
    assert keyring_availability(default_locked=None, collection_locks=[True, True]) == "locked"
    assert keyring_availability(default_locked=None, collection_locks=[False, True]) == "available"


def test_locked_property_is_read_from_the_bus_value():
    class Boxed:
        def unpack(self) -> tuple[bool]:
            return (True,)

    assert _locked_value(Boxed()) is True
    assert _locked_value((False,)) is False

    class Collection:
        def __init__(self, path: str) -> None:
            self.path = path

        def get_object_path(self) -> str:
            return self.path

    login = Collection("/org/freedesktop/secrets/collection/login")
    session = Collection("/org/freedesktop/secrets/collection/session")
    found = _login_collection([session, login])
    assert found is login


def test_live_locked_property_beats_a_stale_cache():
    gi = pytest.importorskip("gi")
    del gi

    class Reply:
        def unpack(self) -> tuple[bool]:
            return (True,)

    class Collection:
        def call_sync(self, method: str, *_args: object) -> Reply:
            assert method == "org.freedesktop.DBus.Properties.Get"
            return Reply()

        def get_locked(self) -> bool:
            return False

    from tetherbot.secrets import _collection_locked

    assert _collection_locked(Collection()) is True


def test_import_does_not_load_secret():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import sys, tetherbot.secrets\n"
        "bad = [name for name in sys.modules if name.startswith('gi')]\n"
        "raise SystemExit(0 if not bad else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env)

# SPDX-License-Identifier: GPL-2.0-or-later
"""Credential helper against a fake secret backend. No network and no files."""

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

from tetherbot.credential import fill, github_https_path, main, parse_attributes
from tetherbot.secrets import MemoryBackend, SecretStore

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ghp_" + ("c" * 36)
REMOTE = "https://github.com/owner/repo.git"
PATH_VALUE = "owner/repo.git"


def _config(path: Path, remote: str = REMOTE) -> None:
    path.write_text(
        "\n".join(
            [
                'schema = "tetherbot/1"',
                "[bridge]",
                'mode = "repo-only"',
                "[adapters.github-poller]",
                "enabled = true",
                f'remote = "{remote}"',
                'auth = "https-token"',
                'branch = "main"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _store() -> SecretStore:
    store = SecretStore(MemoryBackend())
    store.put_github_token("github-token", TOKEN)
    return store


def _run(
    action: str,
    stdin: str,
    tmp_path: Path,
    *,
    store: SecretStore | None = None,
) -> tuple[int, str, str]:
    stdout, stderr = StringIO(), StringIO()
    code = main(
        action.split(),
        stdin=StringIO(stdin),
        stdout=stdout,
        stderr=stderr,
        store=store if store is not None else _store(),
        config_path=tmp_path / "config.toml",
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_get_returns_the_token_only_on_stdout(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _config(tmp_path / "config.toml")
    code, out, err = _run(
        "--slot github-token get",
        f"protocol=https\nhost=github.com\npath={PATH_VALUE}\n\n",
        tmp_path,
    )
    assert code == 0
    assert out == f"username=x-access-token\npassword={TOKEN}\n\n"
    assert err == ""
    assert TOKEN not in err
    assert TOKEN not in (tmp_path / "config.toml").read_text(encoding="utf-8")
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace")


def test_wrong_host_path_and_protocol_get_nothing(tmp_path: Path):
    _config(tmp_path / "config.toml")
    store = _store()
    for stdin in (
        f"protocol=http\nhost=github.com\npath={PATH_VALUE}\n\n",
        f"protocol=https\nhost=github.com.evil\npath={PATH_VALUE}\n\n",
        f"protocol=https\nhost=evilgithub.com\npath={PATH_VALUE}\n\n",
        "protocol=https\nhost=github.com\npath=owner/other.git\n\n",
        "protocol=https\nhost=github.com\n\n",
    ):
        code, out, err = _run("get", stdin, tmp_path, store=store)
        assert code == 0
        assert out == ""
        assert err.strip() == "credential request did not match"
        assert TOKEN not in err
        assert "owner/" not in err
        assert "evil" not in err


def test_store_and_erase_do_not_keep_the_token(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _config(tmp_path / "config.toml")
    blob = f"protocol=https\nhost=github.com\nusername=x-access-token\npassword={TOKEN}\n\n"
    for action in ("store", "erase"):
        code, out, err = _run(action, blob, tmp_path)
        assert code == 0
        assert out == ""
        assert TOKEN not in err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace")


def test_locked_keyring_prints_no_token(tmp_path: Path):
    _config(tmp_path / "config.toml")
    store = SecretStore(MemoryBackend(status="locked"))
    code, out, err = _run(
        "get",
        f"protocol=https\nhost=github.com\npath={PATH_VALUE}\n\n",
        tmp_path,
        store=store,
    )
    assert code == 0
    assert out == ""
    assert TOKEN not in err
    assert "keyring locked" in err


def test_missing_token_is_silent_on_stdout(tmp_path: Path):
    _config(tmp_path / "config.toml")
    code, out, err = _run(
        "get",
        f"protocol=https\nhost=github.com\npath={PATH_VALUE}\n\n",
        tmp_path,
        store=SecretStore(MemoryBackend()),
    )
    assert code == 0
    assert out == ""
    assert TOKEN not in err
    assert err.strip() == "github token is not stored"


def test_missing_config_names_the_reason_without_a_secret(tmp_path: Path):
    code, out, err = _run(
        "get",
        f"protocol=https\nhost=github.com\npath={PATH_VALUE}\n\n",
        tmp_path,
    )
    assert code == 0
    assert out == ""
    assert err.strip() == "github remote is not configured"
    assert TOKEN not in err
    assert PATH_VALUE not in err


def test_port_443_matches_github(tmp_path: Path):
    _config(tmp_path / "config.toml")
    code, out, _err = _run(
        "get",
        f"protocol=https\nhost=github.com:443\npath=/{PATH_VALUE}\n\n",
        tmp_path,
    )
    assert code == 0
    assert f"password={TOKEN}" in out


def test_userinfo_remote_is_not_an_allowed_path():
    assert github_https_path(REMOTE) == PATH_VALUE
    assert github_https_path("https://user:token@github.com/owner/repo.git") is None
    assert github_https_path("https://example.test/owner/repo.git") is None
    assert github_https_path("file:///tmp/repo.git") is None


def test_fill_refuses_a_token_with_a_newline():
    attributes = parse_attributes(f"protocol=https\nhost=github.com\npath={PATH_VALUE}\n")
    assert fill(attributes, token="abc\ndef", allowed=PATH_VALUE) == ""


def test_helper_import_does_not_open_a_socket():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import socket, sys\n"
        "def explode(*args, **kwargs):\n"
        "    raise AssertionError('socket')\n"
        "socket.socket = explode\n"
        "socket.create_connection = explode\n"
        "import tetherbot.credential\n"
        "raise SystemExit(0)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env, timeout=30)

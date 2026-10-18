# SPDX-License-Identifier: GPL-2.0-or-later
"""git credential helper for one GitHub HTTPS remote.

Git runs ``git-credential-tetherbot [--slot SLOT] get``. Attributes arrive
on stdin. A matching get writes ``username=x-access-token`` and
``password=...`` to stdout. The token is read from libsecret
(``kind=github-token``) and is not logged, stored in a file, or placed in
argv. ``store`` and ``erase`` discard stdin and write nothing, so git cannot
save the token into ``.git/config`` or a credential cache of its own.

The helper answers only ``protocol=https``, ``host=github.com``, and the
exact path of the ``github-poller`` remote in ``config.toml``.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tetherbot.config import ConfigError, load_config
from tetherbot.model import looks_like_secret
from tetherbot.secrets import (
    SecretError,
    SecretLocked,
    SecretStore,
    SecretValueError,
    open_secret_store,
)

GITHUB_HOST = "github.com"
GITHUB_TOKEN_SLOT = "github-token"
_MAX_STDIN = 65536


def find_credential_helper() -> str | None:
    """Return the installed helper executable, or None when it is absent."""

    found = shutil.which("git-credential-tetherbot")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "git-credential-tetherbot"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def helper_spec(helper: str, slot: str = GITHUB_TOKEN_SLOT) -> str:
    """The ``credential.helper`` value git stores for this clone."""

    return f"{helper} --slot {slot}"


def github_https_path(remote: str) -> str | None:
    """Return ``owner/repo.git`` for a plain ``https://github.com`` remote."""

    if not remote or looks_like_secret(remote):
        return None
    parts = urlsplit(remote)
    if parts.scheme != "https" or parts.hostname != GITHUB_HOST:
        return None
    if parts.username or parts.password:
        return None
    return _clean_path(unquote(parts.path))


def parse_attributes(text: str) -> dict[str, str]:
    """Parse git credential attributes. A blank line ends the record."""

    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            break
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key:
            found[key] = value
    return found


def fill(attributes: Mapping[str, str], *, token: str | None, allowed: str | None) -> str:
    """Return the get response, or ``""`` when this request is not ours.

    The token appears only as the ``password`` line. A newline in the token
    is refused so it cannot break the protocol record.
    """

    if not token or not allowed or any(char in token for char in "\r\n\x00"):
        return ""
    if attributes.get("protocol") != "https":
        return ""
    if _request_host(attributes.get("host", "")) != GITHUB_HOST:
        return ""
    if _clean_path(attributes.get("path", "")) != allowed:
        return ""
    return f"username=x-access-token\npassword={token}\n\n"


def allowed_github_path(config_path: Path) -> str | None:
    """The one https path this helper may answer, from ``config.toml``."""

    if not config_path.is_file():
        return None
    try:
        config = load_config(config_path)
    except ConfigError:
        return None
    row = config.adapters.get("github-poller")
    if row is None or not row.remote:
        return None
    return github_https_path(row.remote)


def main(
    argv: list[str] | None = None,
    *,
    stdin: object | None = None,
    stdout: object | None = None,
    stderr: object | None = None,
    store: SecretStore | None = None,
    config_path: Path | None = None,
) -> int:
    """Run one helper invocation. Secrets are not written to stderr."""

    args = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parsed = _parse_args(args)
    if parsed is None:
        print("usage: git-credential-tetherbot [--slot SLOT] {get,store,erase}", file=err)
        return 2
    action, slot = parsed
    incoming = sys.stdin if stdin is None else stdin
    raw = incoming.read(_MAX_STDIN)  # type: ignore[attr-defined]
    if incoming.read(1):  # type: ignore[attr-defined]
        return 0
    if action != "get":
        return 0
    secrets = store if store is not None else open_secret_store()
    try:
        token = secrets.get_github_token(slot)
    except SecretLocked:
        print("keyring locked", file=err)
        return 0
    except SecretValueError:
        print("slot is invalid", file=err)
        return 2
    except SecretError:
        print("secret service is not available", file=err)
        return 0
    attributes = parse_attributes(str(raw))
    path = allowed_github_path(_config_path(config_path))
    body = fill(attributes, token=token, allowed=path)
    if not token and path and _request_matches(attributes, path):
        print("github token is not stored", file=err)
    if body:
        out.write(body)  # type: ignore[attr-defined]
    return 0


def _request_matches(attributes: Mapping[str, str], allowed: str) -> bool:
    return (
        attributes.get("protocol") == "https"
        and _request_host(attributes.get("host", "")) == GITHUB_HOST
        and _clean_path(attributes.get("path", "")) == allowed
    )


def _config_path(path: Path | None) -> Path:
    if path is not None:
        return path
    from tetherbot.daemon import default_config_path

    return default_config_path()


def _parse_args(argv: list[str]) -> tuple[str, str] | None:
    slot = GITHUB_TOKEN_SLOT
    action = ""
    index = 0
    while index < len(argv):
        arg = argv[index]
        if looks_like_secret(arg):
            return None
        if arg == "--slot":
            if index + 1 >= len(argv):
                return None
            slot = argv[index + 1]
            if looks_like_secret(slot):
                return None
            index += 2
            continue
        if arg.startswith("-") or action:
            return None
        action = arg
        index += 1
    if action not in {"get", "store", "erase"}:
        return None
    return action, slot


def _request_host(raw: str) -> str:
    host = raw.strip().lower()
    if host.endswith(":443"):
        host = host[: -len(":443")]
    return host


def _clean_path(raw: str) -> str | None:
    path = unquote(raw).strip("/")
    if not path or "\\" in path:
        return None
    parts = path.split("/")
    if ".." in parts or any(not part or part == "." for part in parts):
        return None
    return path


if __name__ == "__main__":
    raise SystemExit(main())

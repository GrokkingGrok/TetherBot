# SPDX-License-Identifier: GPL-2.0-or-later
"""Inbound poll and owned-path write-back for one private git repo.

A poll starts with ``git ls-remote``. The clone is updated only when that
SHA changes. Feed files are schema-gated: a bad file stays stale and is not
replaced with an empty list. The bridge stages only ``desktop/`` and
``log/desktop/``. A rebase conflict aborts the rebase and fails closed.

``https-token`` runs git through ``git-credential-tetherbot``. The token
stays in libsecret and is not put in a remote URL, ``.git/config``, argv,
or the log. Git's ``HOME`` is a private directory and its global config is
``/dev/null``. The helper still receives the user's XDG config and data
directories, plus the session bus when it is set, so it can find the app,
``config.toml``, and libsecret. A failed ``ls-remote`` is logged as
``ls-remote failed: auth`` or ``ls-remote failed: network``. Git's own
output is not logged. ``ssh-deploy-key`` stays deferred and does not spawn git.
``desktop/outbox`` is still a v0.2 path. A rejected push or a stale feed
does not stretch the poll interval: the next ``ls-remote`` stays on
``poll_seconds``. Transport failures still back off. Importing this module
does not import PyGObject.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from tetherbot import SCHEMA_VERSION
from tetherbot.adapters.base import AdapterStatus, PollResult, SendResult
from tetherbot.credential import find_credential_helper, helper_spec
from tetherbot.files import ensure_private_dir, write_private_json
from tetherbot.model import Item, looks_like_secret, mask_secrets
from tetherbot.store import StoreUpdate
from tetherbot.version_gate import check_schema

_LOG = logging.getLogger("tetherbot")
_MAX_BACKOFF = 15 * 60
_LOCK_STRETCH = 600
_PUSH_TRIES = 3
_COMMIT_MESSAGE = "Update desktop state"
_HELPER_BUS_ENV = ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
_AUTH_STDERR = (
    "keyring locked",
    "secret service is not available",
    "github token is not stored",
    "slot is invalid",
    "github remote is not configured",
    "credential request did not match",
    "credential request refused",
    "app is not installed",
    "authentication failed",
    "could not read username",
    "terminal prompts disabled",
    "invalid username or token",
    "password authentication",
    "returned error: 401",
    "returned error: 403",
)
_IDENTITY = (
    "-c",
    "user.name=TetherBot",
    "-c",
    "user.email=noreply@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "safe.directory=*",
    "-c",
    "core.autocrlf=false",
)

GitRun = Callable[[list[str], Path | None], "GitResult"]


@dataclass(frozen=True)
class GitResult:
    code: int
    stdout: str
    stderr: str


def _git_child_env(home: Path) -> dict[str, str]:
    """Environment git, and then the credential helper, actually run with.

    ``HOME`` stays on the private git directory and both global git configs
    point at ``os.devnull``, so a user gitconfig cannot change the remote.
    ``XDG_CONFIG_HOME`` and ``XDG_DATA_HOME`` stay on the real user (the
    parent environment when set, otherwise that user's ``.config`` and
    ``.local/share``). The session bus variables are copied only when set.
    Nothing else from the parent environment is copied.
    """

    desktop = _desktop_home()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "TetherBot",
        "GIT_AUTHOR_EMAIL": "noreply@localhost",
        "GIT_COMMITTER_NAME": "TetherBot",
        "GIT_COMMITTER_EMAIL": "noreply@localhost",
        "XDG_CONFIG_HOME": _env_or_default("XDG_CONFIG_HOME", desktop / ".config"),
        "XDG_DATA_HOME": _env_or_default("XDG_DATA_HOME", desktop / ".local" / "share"),
    }
    for name in _HELPER_BUS_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    return env


def _desktop_home() -> Path:
    raw = os.environ.get("HOME", "").strip()
    if raw:
        return Path(raw)
    return Path.home()


def _env_or_default(name: str, fallback: Path) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else str(fallback)


def _ls_remote_reason(result: GitResult) -> str:
    """Classify a failed ls-remote without copying git's output.

    The label is ``auth`` or ``network``. stdout and stderr can contain a
    token, so they are not returned and must not be logged.
    """

    folded = f"{result.stderr}\n{result.stdout}".casefold()
    kind = "auth" if any(marker in folded for marker in _AUTH_STDERR) else "network"
    return f"ls-remote failed: {kind}"


class SubprocessGit:
    """Run git with a private environment. stdout and stderr are not logged."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def __call__(self, args: list[str], cwd: Path | None) -> GitResult:
        return self.run(args, cwd)

    def run(self, args: list[str], cwd: Path | None) -> GitResult:
        if any(looks_like_secret(arg) for arg in args):
            return GitResult(1, "", "")
        env = _git_child_env(self.home)
        try:
            completed = subprocess.run(
                ["git", *_IDENTITY, *args],
                cwd=None if cwd is None else str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return GitResult(1, "", "")
        return GitResult(completed.returncode, completed.stdout, completed.stderr)


class GitHubPoller:
    name = "github-poller"
    direction = frozenset({"inbound", "outbound"})

    def __init__(
        self,
        *,
        git: GitRun | None = None,
        online: Callable[[], bool] | None = None,
        locked: Callable[[], bool] | None = None,
        credential_helper: str | None = None,
    ) -> None:
        self._git = git
        self._online = online if online is not None else (lambda: True)
        self._locked = locked if locked is not None else (lambda: False)
        self._credential_helper = credential_helper
        self._discovered_helper: str | None = None
        self._https_ready: set[str] = set()
        self._ctx: object | None = None
        self._running = False
        self._closed = False
        self._next: datetime | None = None
        self._backoff = 0
        self._sha = ""
        self._needs_push = False
        self.overlay: tuple[str, str] | None = None
        self.stale: list[str] = []
        self.last_error = ""

    def start(self, ctx: object | None = None) -> None:
        self._ctx = ctx
        self._running = True
        self._load_sha()
        self._inspect()

    def stop(self) -> None:
        self._running = False
        self._ctx = None

    def poll(self) -> PollResult:
        self.tick(force=True)
        return PollResult(items=[], errors=list(self.stale), stale_sources=list(self.stale))

    def send(self, bot: str, batch: list[object]) -> SendResult:
        del bot, batch
        return SendResult(status="unavailable", detail="github-poller does not send webhooks")

    def status(self) -> AdapterStatus:
        if not self._running:
            return AdapterStatus(self.name, False, "disabled", "")
        if self._closed:
            detail = self.last_error or "rebase conflict"
            return AdapterStatus(self.name, True, "failed-closed", detail)
        if self.overlay is not None:
            state = "offline" if self.overlay[0] == "offline" else "degraded"
            return AdapterStatus(self.name, True, state, self.overlay[1])
        return AdapterStatus(self.name, True, "running", self.last_error)

    def next_poll(self) -> int:
        if self._next is None:
            return 0
        return int(self._next.timestamp())

    def tick(self, *, force: bool = False) -> None:
        ctx = self._ctx
        if not self._running or ctx is None or self._closed:
            return
        now = ctx.now()
        if not self._online():
            self._set_overlay("offline", "offline")
            return
        if self.overlay == ("offline", "offline"):
            self._clear_overlay()
        if not force and self._next is not None and now < self._next and not self._burst_due(now):
            return
        self._consume_burst(now)
        remote = self._remote()
        kind = self._route_kind()
        if kind == "https" and self._keyring_locked():
            self.last_error = "keyring locked"
            self._set_overlay("degraded", "keyring locked")
            self._schedule_transport_failure(now)
            return
        if kind == "https" and not self._resolved_helper():
            self._refuse("https")
            self._schedule_transport_failure(now)
            return
        if kind not in {"file", "https"}:
            self._refuse(kind)
            self._schedule_transport_failure(now)
            return
        clone = self._clone_dir(remote)
        if clone is None:
            self._schedule_transport_failure(now)
            return
        if (clone / ".git").is_dir() and not self._ensure_https_credentials(clone):
            self._schedule_transport_failure(now)
            return
        sha, probed = self._ls_remote(remote)
        if sha is None:
            reason = _ls_remote_reason(probed)
            self.last_error = reason
            self._set_overlay("degraded", reason)
            _LOG.info("github-poller %s", reason)
            self._schedule_transport_failure(now)
            return
        if sha == self._sha and (clone / ".git").is_dir():
            if self._needs_push:
                self._push_with_retry(clone)
                if not self._closed and not self._needs_push:
                    self._remember_remote(remote)
            if self.stale and not self._closed:
                self._read_tree(clone)
            self._finish_readable(now, changed=False)
            return
        if not (clone / ".git").is_dir():
            if not self._clone(remote, clone):
                self._schedule_transport_failure(now)
                return
        elif not self._pull(clone):
            self._schedule_transport_failure(now)
            return
        self._read_tree(clone)
        self._write_state(clone)
        if not self._closed and not self._needs_push:
            self._remember_remote(remote)
        else:
            self._sha = sha
            self._store_sha()
        self._finish_readable(now, changed=True)

    def commit_paths(self, paths: list[str]) -> bool:
        """Stage owned paths only. A refused path is not passed to git."""

        ctx = self._ctx
        if ctx is None or self._closed:
            return False
        if not paths or any(not owned_repo_path(path) for path in paths):
            _LOG.info("github-poller refused an unowned path")
            return False
        remote = self._remote()
        kind = self._route_kind()
        if kind == "https":
            if not self._resolved_helper():
                return False
        elif kind != "file":
            return False
        clone = self._clone_dir(remote)
        if clone is None or not (clone / ".git").is_dir():
            return False
        if not self._ensure_https_credentials(clone):
            return False
        for path in paths:
            if not (clone / path).is_file():
                return False
        if not self._porcelain(clone, paths):
            return True
        added = self._run_scoped(["add", "--", *paths], clone)
        if added.code != 0:
            return False
        committed = self._run_scoped(["commit", "-m", _COMMIT_MESSAGE], clone)
        if committed.code != 0:
            return False
        return self._push_with_retry(clone)

    def _inspect(self) -> None:
        kind = self._route_kind()
        if kind == "file":
            return
        if kind == "https" and self._keyring_locked():
            self.last_error = "keyring locked"
            self._set_overlay("degraded", "keyring locked")
            return
        if kind == "https" and self._resolved_helper():
            return
        self._refuse(kind)

    def _refuse(self, transport: str) -> None:
        if transport == "https":
            reason = "credential helper is not installed"
        elif transport == "ssh":
            reason = "deploy key is not configured"
        elif transport == "credentials":
            reason = "remote must not contain credentials"
        elif transport in {"", "missing"}:
            reason = "remote is missing"
        else:
            reason = "remote is not allowed"
        self.last_error = reason
        self._set_overlay("degraded", reason)

    def _read_tree(self, clone: Path) -> None:
        ctx = self._ctx
        assert ctx is not None
        errors: list[str] = []
        stale: list[str] = []
        feed = clone / "feed"
        if feed.is_dir():
            for path in sorted(feed.glob("*.json")):
                source = f"feed/{path.name}"
                items, problem = _read_feed(path, source)
                if problem is not None:
                    errors.append(problem)
                    stale.append(source)
                    continue
                update = ctx.store.replace_origin(source, items, now=ctx.now())
                self._emit_store(ctx, update)
        state_path = clone / "desktop" / "state.json"
        if state_path.is_file():
            problem = _read_state(state_path)
            if problem is not None:
                errors.append(problem)
                stale.append("desktop/state.json")
        self.stale = stale
        if errors:
            self.last_error = mask_secrets("; ".join(errors))[:200]
            self._set_overlay("degraded", self.last_error)
        else:
            self.stale = []

    def _write_state(self, clone: Path) -> None:
        ctx = self._ctx
        assert ctx is not None
        payload = {
            "schema": SCHEMA_VERSION,
            "items": [
                {
                    "done_locally": item.done_locally,
                    "key": item.key,
                    "seen": item.seen,
                    "snoozed_until": item.snoozed_until,
                    "status": item.status,
                }
                for item in ctx.store.items()
            ],
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        path = clone / "desktop" / "state.json"
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.commit_paths(["desktop/state.json"])

    def _push_with_retry(self, clone: Path) -> bool:
        for attempt in range(_PUSH_TRIES):
            pushed = self._run_scoped(["push"], clone)
            if pushed.code == 0:
                self._needs_push = False
                return True
            if attempt == _PUSH_TRIES - 1:
                break
            pulled = self._run_scoped(["pull", "--rebase", "--autostash"], clone)
            if pulled.code != 0:
                if _rebase_in_progress(clone):
                    self._run_scoped(["rebase", "--abort"], clone)
                self._needs_push = True
                self._close("rebase conflict")
                return False
        self._needs_push = True
        _LOG.info("github-poller push rejected")
        if self.stale:
            return False
        self.last_error = "push rejected"
        self._set_overlay("degraded", "push rejected")
        return False

    def _clone(self, remote: str, dest: Path) -> bool:
        branch = self._branch()
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_scoped(
            ["clone", "--branch", branch, "--", remote, str(dest)],
            None,
        )
        if result.code != 0:
            self.last_error = "clone failed"
            self._set_overlay("degraded", "clone failed")
            _LOG.info("github-poller clone failed")
            return False
        return self._ensure_https_credentials(dest)

    def _pull(self, clone: Path) -> bool:
        if not self._ensure_https_credentials(clone):
            return False
        result = self._run_scoped(["pull", "--rebase", "--autostash"], clone)
        if result.code == 0:
            return True
        if _rebase_in_progress(clone):
            self._run_scoped(["rebase", "--abort"], clone)
            self._close("rebase conflict")
            return False
        self.last_error = "pull failed"
        self._set_overlay("degraded", "pull failed")
        _LOG.info("github-poller pull failed")
        return False

    def _ls_remote(self, remote: str) -> tuple[str | None, GitResult]:
        result = self._run_scoped(["ls-remote", "--", remote, f"refs/heads/{self._branch()}"], None)
        if result.code != 0:
            return None, result
        return _parse_sha(result.stdout), result

    def _porcelain(self, clone: Path, paths: list[str]) -> bool:
        result = self._run_scoped(["status", "--porcelain", "--", *paths], clone)
        return bool(result.stdout.strip())

    def _run(self, args: list[str], cwd: Path | None) -> GitResult:
        runner = self._git
        if runner is None:
            ctx = self._ctx
            home = Path(".") if ctx is None else ctx.state_dir / "git-home"
            ensure_private_dir(home)
            runner = SubprocessGit(home)
            self._git = runner
        return runner(args, cwd)

    def _run_scoped(self, args: list[str], cwd: Path | None) -> GitResult:
        if self._route_kind() == "https":
            prefix = self._credential_prefix()
            if prefix:
                args = [*prefix, *args]
        return self._run(args, cwd)

    def _credential_prefix(self) -> list[str]:
        helper = self._resolved_helper()
        if not helper:
            return []
        spec = helper_spec(helper)
        if looks_like_secret(spec):
            return []
        return [
            "-c",
            "credential.helper=",
            "-c",
            f"credential.helper={spec}",
            "-c",
            "credential.useHttpPath=true",
        ]

    def _resolved_helper(self) -> str:
        if self._credential_helper is not None:
            return self._credential_helper
        if self._discovered_helper is None:
            found = find_credential_helper()
            self._discovered_helper = found or ""
        return self._discovered_helper

    def _ensure_https_credentials(self, clone: Path) -> bool:
        if self._route_kind() != "https":
            return True
        key = str(clone)
        if key in self._https_ready:
            return True
        helper = self._resolved_helper()
        if not helper:
            self._refuse("https")
            return False
        if not configure_https_credentials(self._run, clone, helper):
            self.last_error = "credential helper is not installed"
            self._set_overlay("degraded", self.last_error)
            _LOG.info("github-poller credential setup failed")
            return False
        self._https_ready.add(key)
        return True

    def _keyring_locked(self) -> bool:
        ctx = self._ctx
        secrets = None if ctx is None else getattr(ctx, "secrets", None)
        if secrets is None:
            return False
        try:
            return secrets.status() == "locked"
        except Exception:
            return False

    def _route_kind(self) -> str:
        remote = self._remote()
        transport = _transport(remote)
        if transport == "file":
            return "file"
        if transport == "credentials":
            return "credentials"
        if self._auth() == "ssh-deploy-key" or transport == "ssh":
            return "ssh"
        if transport == "https":
            return "https"
        if not transport:
            return "missing"
        return transport

    def _auth(self) -> str:
        ctx = self._ctx
        if ctx is None or ctx.config is None:
            return ""
        row = ctx.config.adapters.get(self.name)
        if row is None or not row.auth:
            return ""
        return str(row.auth)

    def _clone_dir(self, remote: str) -> Path | None:
        ctx = self._ctx
        if ctx is None:
            return None
        name = _repo_name(remote)
        ensure_private_dir(ctx.repos_dir)
        return ctx.repos_dir / name

    def _remote(self) -> str:
        ctx = self._ctx
        if ctx is None or ctx.config is None:
            return ""
        row = ctx.config.adapters.get(self.name)
        if row is None or not row.remote:
            return ""
        return str(row.remote)

    def _branch(self) -> str:
        ctx = self._ctx
        if ctx is None or ctx.config is None:
            return "main"
        row = ctx.config.adapters.get(self.name)
        if row is None or not row.branch:
            return "main"
        return str(row.branch)

    def _interval(self) -> int:
        ctx = self._ctx
        if ctx is None or ctx.config is None:
            return 120
        row = ctx.config.adapters.get(self.name)
        if row is None or row.poll_seconds is None:
            return 120
        return int(row.poll_seconds)

    def _finish_readable(self, now: datetime, *, changed: bool) -> None:
        """Schedule the next poll at the normal interval.

        A stale feed or a rejected push is a successful read of the remote.
        Neither one may grow the transport backoff, or a later fix sits
        unseen until the delay hits 15 minutes.
        """

        if self._closed:
            self._schedule_poll(now)
            return
        if not self.stale and not self._needs_push:
            self._clear_overlay()
            self.last_error = ""
            _LOG.info("github-poller updated" if changed else "github-poller unchanged")
        elif self.stale:
            _LOG.info("github-poller stale")
        self._schedule_poll(now)

    def _schedule_poll(self, now: datetime) -> None:
        self._schedule(now, failed=False)

    def _schedule_transport_failure(self, now: datetime) -> None:
        self._schedule(now, failed=True)

    def _schedule(self, now: datetime, *, failed: bool) -> None:
        interval = self._interval()
        if self._locked():
            interval = max(interval, _LOCK_STRETCH)
        if failed:
            if self._backoff == 0:
                self._backoff = interval
            else:
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)
            delay = self._backoff
        else:
            self._backoff = 0
            delay = interval
        self._next = now + timedelta(seconds=delay)

    def _burst_due(self, now: datetime) -> bool:
        sender = getattr(self._ctx, "webhook", None)
        if sender is None:
            return False
        return any(moment <= now for moment in getattr(sender, "poll_burst", ()))

    def _consume_burst(self, now: datetime) -> None:
        sender = getattr(self._ctx, "webhook", None)
        if sender is None:
            return
        burst = getattr(sender, "poll_burst", ())
        sender.poll_burst = tuple(moment for moment in burst if moment > now)

    def _emit_store(self, ctx: object, update: StoreUpdate) -> None:
        api = getattr(ctx, "api", None)
        if api is None:
            return
        diff = update.diff
        if diff.added or diff.updated or diff.removed:
            api.emit_items_changed(list(diff.added), list(diff.updated), list(diff.removed))
        for notice in update.notifications:
            text = json.dumps(
                notice.item.protocol_dict(),
                sort_keys=True,
                separators=(",", ":"),
            )
            api.emit_notification(mask_secrets(text), notice.reason)

    def _remember_remote(self, remote: str) -> None:
        refreshed, _probed = self._ls_remote(remote)
        if refreshed is None:
            return
        self._sha = refreshed
        self._store_sha()

    def _close(self, reason: str) -> None:
        self._closed = True
        self.last_error = reason
        self.overlay = ("failed_closed", reason)
        _LOG.info("github-poller %s", reason)
        ctx = self._ctx
        if ctx is not None:
            ctx.publish_overlay()

    def _set_overlay(self, state: str, reason: str) -> None:
        self.overlay = (state, reason)
        ctx = self._ctx
        if ctx is not None:
            ctx.publish_overlay()

    def _clear_overlay(self) -> None:
        if self._closed or self.overlay is None:
            return
        self.overlay = None
        ctx = self._ctx
        if ctx is not None:
            ctx.publish_overlay()

    def _load_sha(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        path = ctx.state_dir / "poller.json"
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        sha = raw.get("sha") if isinstance(raw, dict) else None
        if isinstance(sha, str):
            self._sha = sha

    def _store_sha(self) -> None:
        ctx = self._ctx
        if ctx is None or not self._sha:
            return
        write_private_json(
            ctx.state_dir / "poller.json",
            {"schema": SCHEMA_VERSION, "sha": self._sha},
        )


def configure_https_credentials(git: GitRun, clone: Path, helper: str) -> bool:
    """Point one clone at the bridge helper. The token is not written.

    ``credential.helper`` is reset to empty, then set to the helper, and
    ``credential.useHttpPath`` is turned on. The change is local to ``clone``.
    """

    if not helper or looks_like_secret(helper) or not (clone / ".git").is_dir():
        return False
    spec = helper_spec(helper)
    if looks_like_secret(spec):
        return False
    git(["config", "--local", "--unset-all", "credential.helper"], clone)
    blank = git(["config", "--local", "--add", "credential.helper", ""], clone)
    added = git(["config", "--local", "--add", "credential.helper", spec], clone)
    flag = git(["config", "--local", "credential.useHttpPath", "true"], clone)
    return blank.code == 0 and added.code == 0 and flag.code == 0


def owned_repo_path(path: str) -> bool:
    """True when ``path`` is a bridge-owned file under desktop/ or log/desktop/."""

    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = Path(path).parts
    if ".." in parts or not parts:
        return False
    if parts[0] == "desktop":
        return len(parts) >= 2
    return len(parts) >= 3 and parts[0] == "log" and parts[1] == "desktop"


def _transport(remote: str) -> str:
    if not remote:
        return ""
    if remote.startswith("git@github.com:"):
        return "ssh"
    parts = urlsplit(remote)
    if parts.username or parts.password:
        return "credentials"
    if parts.scheme == "file" and parts.path.startswith("/"):
        return "file"
    if parts.scheme == "https" and parts.hostname:
        return "https"
    return "rejected"


def _repo_name(remote: str) -> str:
    name = Path(urlsplit(remote).path).name
    if name.endswith(".git"):
        name = name[: -len(".git")]
    cleaned = "".join(char if char.isalnum() or char == "-" else "-" for char in name.lower())
    cleaned = cleaned.strip("-")
    return cleaned or "data"


def _parse_sha(text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    sha = lines[0].split()[0]
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        return None
    return sha


def _rebase_in_progress(clone: Path) -> bool:
    git_dir = clone / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _read_feed(path: Path, source: str) -> tuple[list[Item], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], f"{source} is unreadable"
    if not isinstance(payload, dict):
        return [], f"{source} is unreadable"
    decision = check_schema(payload.get("schema"), source=source)
    if not decision.accepted:
        return [], decision.message
    bot = payload.get("bot")
    if bot != path.stem:
        return [], f"{source} is invalid"
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return [], f"{source} is invalid"
    origin = source
    try:
        items = [Item.from_mapping(entry, bot=bot, origin=origin) for entry in raw_items]
    except (TypeError, ValueError):
        return [], f"{source} is invalid"
    return items, None


def _read_state(path: Path) -> str | None:
    source = "desktop/state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"{source} is unreadable"
    if not isinstance(payload, dict):
        return f"{source} is unreadable"
    decision = check_schema(payload.get("schema"), source=source)
    if not decision.accepted:
        return decision.message
    return None

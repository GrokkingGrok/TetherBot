# SPDX-License-Identifier: GPL-2.0-or-later
"""github-poller against a local bare repo.

ssh never runs git. https runs git only when a credential helper is configured,
and the token is not part of the git command.
"""

import json
import os
import shlex
import stat
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import urlsplit

from tests.helpers import NOW
from tetherbot.adapters.github_poller import (
    GitHubPoller,
    GitResult,
    SubprocessGit,
    configure_https_credentials,
    owned_repo_path,
)
from tetherbot.config import AdapterConfig, BridgeConfig, QueueConfig
from tetherbot.daemon import BridgeDaemon
from tetherbot.store import ItemStore

ROOT = Path(__file__).resolve().parents[1]
KEY = "primary/primary-20261017-01"


class Clock:
    def __init__(self) -> None:
        self.current = NOW

    def __call__(self):
        return self.current


class ScriptedGit:
    def __init__(self, *, pushes: int) -> None:
        self.pushes = pushes
        self.names: list[str] = []

    def __call__(self, args: list[str], cwd: Path | None) -> GitResult:
        del cwd
        name = args[0]
        self.names.append(name)
        if name == "status":
            return GitResult(0, " M desktop/state.json\n", "")
        if name == "push":
            if self.names.count("push") < self.pushes:
                return GitResult(1, "", "rejected")
            return GitResult(0, "", "")
        if name == "pull":
            return GitResult(0, "", "")
        return GitResult(0, "", "")


def _git(cwd: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    command = [
        "git",
        "-c",
        "user.name=Tester",
        "-c",
        "user.email=tester@example.com",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "init.defaultBranch=main",
        "-c",
        "safe.directory=*",
        *args,
    ]
    return subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _feed(title: str = "Approve the sample request or turn it down") -> dict:
    return {
        "schema": "tetherbot/1",
        "bot": "primary",
        "updated_at": "2026-10-17T12:00:00+00:00",
        "status": {"state": "idle", "summary": "Example feed."},
        "items": [
            {
                "id": "primary-20261017-01",
                "kind": "ask",
                "title": title,
                "body": "Fixture item. Not a real task.",
                "status": "open",
                "created": "2026-10-17T11:40:00+00:00",
                "updated_at": "2026-10-17T11:40:00+00:00",
                "notify": True,
                "actions": ["approve", "veto"],
                "source": {"bot": "primary", "routine": "example"},
            }
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed(tmp_path: Path) -> str:
    bare = tmp_path / "repo.git"
    _git(None, "init", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git(None, "init", "-b", "main", str(seed))
    _write_json(seed / "feed" / "primary.json", _feed())
    _git(seed, "add", "feed/primary.json")
    _git(seed, "commit", "-m", "seed feed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", "main")
    return bare.resolve().as_uri()


def _config(remote: str, *, auth: str | None = None, poll: int = 60) -> str:
    lines = [
        'schema = "tetherbot/1"',
        "[bridge]",
        'mode = "repo-only"',
        "[adapters.github-poller]",
        "enabled = true",
        f'remote = "{remote}"',
        'branch = "main"',
        f"poll_seconds = {poll}",
    ]
    if auth is not None:
        lines.append(f'auth = "{auth}"')
    return "\n".join(lines) + "\n"


def _recording(home: Path):
    home.mkdir(parents=True, exist_ok=True)
    inner = SubprocessGit(home)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path | None) -> GitResult:
        calls.append(list(args))
        return inner.run(args, cwd)

    return run, calls


def _start(
    tmp_path: Path,
    remote: str,
    *,
    poll: int = 60,
    git=None,
    online=None,
    locked=None,
    auth: str | None = None,
    credential_helper: str | None = None,
):
    clock = Clock()
    path = tmp_path / "config.toml"
    path.write_text(_config(remote, auth=auth, poll=poll), encoding="utf-8")
    daemon = BridgeDaemon(
        config_path=path,
        state_dir=tmp_path / "state",
        repos_dir=tmp_path / "repos",
        log_stream=StringIO(),
        clock=clock,
        poller_git=git,
        poller_online=online,
        poller_locked=locked,
        poller_credential_helper=credential_helper,
    )
    daemon.start()
    return daemon, clock


def _bare(remote: str) -> Path:
    return Path(urlsplit(remote).path)


def _clone(daemon: BridgeDaemon) -> Path:
    return daemon.repos_dir / "repo"


def _push(tmp_path: Path, bare: Path, message: str, writer) -> None:
    side = tmp_path / "side-work"
    if side.exists():
        subprocess.run(["rm", "-rf", str(side)], check=True, timeout=30)
    _git(None, "clone", str(bare), str(side))
    writer(side)
    _git(side, "add", "-A")
    _git(side, "commit", "-m", message)
    _git(side, "push", "origin", "HEAD:main")


def _ctx(tmp_path: Path, remote: str):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    return type(
        "Ctx",
        (),
        {
            "store": ItemStore(state / "items.json"),
            "state_dir": state,
            "repos_dir": tmp_path / "repos",
            "config": BridgeConfig(
                schema="tetherbot/1",
                mode="repo-only",
                adapters={
                    "github-poller": AdapterConfig(
                        enabled=True,
                        remote=remote,
                        branch="main",
                        poll_seconds=60,
                    )
                },
                sinks={},
                bots={},
                queue=QueueConfig(),
            ),
            "api": None,
            "webhook": None,
            "now": lambda self=None: NOW,
            "publish_overlay": lambda self=None: None,
        },
    )()


def test_owned_repo_path_rejects_feed_and_parents():
    assert owned_repo_path("desktop/state.json") is True
    assert owned_repo_path("log/desktop/2026-10.jsonl") is True
    assert owned_repo_path("feed/primary.json") is False
    assert owned_repo_path("desktop/../feed/primary.json") is False
    assert owned_repo_path("/etc/passwd") is False
    assert owned_repo_path("desktop") is False


def test_poll_reads_feed_and_commits_only_owned_state(tmp_path: Path):
    remote = _seed(tmp_path)
    daemon, _clock = _start(tmp_path, remote)
    assert daemon.api is not None
    seen: list[tuple[str, tuple]] = []
    daemon.api.subscribe(lambda name, payload: seen.append((name, payload)))
    daemon.tick_poller()
    assert daemon.state == "ok"
    assert daemon.reason == ""
    item = daemon.store.get(KEY)
    assert item is not None
    assert item.title.startswith("Approve")
    clone = _clone(daemon)
    assert (clone / "desktop" / "state.json").is_file()
    state = json.loads((clone / "desktop" / "state.json").read_text(encoding="utf-8"))
    assert state["schema"] == "tetherbot/1"
    assert state["items"][0]["key"] == KEY
    assert "title" not in state["items"][0]
    identity = _git(clone, "log", "-1", "--format=%an%n%ae%n%s")
    assert identity.stdout == "TetherBot\nnoreply@localhost\nUpdate desktop state\n"
    assert daemon.poller.commit_paths(["feed/primary.json"]) is False
    assert daemon.poller.commit_paths(["desktop/../feed/primary.json"]) is False
    cached = _git(clone, "diff", "--cached", "--name-only")
    assert cached.stdout == ""
    saved = json.loads((daemon.state_dir / "poller.json").read_text(encoding="utf-8"))
    assert stat.S_IMODE((daemon.state_dir / "poller.json").stat().st_mode) == 0o600
    assert "file:" not in (daemon.state_dir / "poller.json").read_text(encoding="utf-8")
    log = (daemon.state_dir / "bridge.log").read_text(encoding="utf-8")
    assert saved["sha"] not in log
    assert stat.S_IMODE((daemon.state_dir / "git-home").stat().st_mode) == 0o700
    added = [payload for name, payload in seen if name == "ItemsChanged"]
    notes = [payload for name, payload in seen if name == "NotificationRequested"]
    assert KEY in added[0][0]
    assert notes[0][1] == "new"
    assert "Approve" in notes[0][0]
    rows = json.loads(daemon.api.call("GetAdapters", ())[0])
    poller = next(row for row in rows if row["name"] == "github-poller")
    assert poller["state"] == "running"
    assert poller["version_gate"] == "tetherbot/1"
    assert poller["next_poll"] == int((NOW + timedelta(seconds=60)).timestamp())
    daemon.stop()
    assert daemon.poller is None


def test_unchanged_sha_runs_only_ls_remote(tmp_path: Path):
    remote = _seed(tmp_path)
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    mark = len(calls)
    clock.current += timedelta(seconds=59)
    daemon.tick_poller()
    assert len(calls) == mark
    clock.current += timedelta(seconds=1)
    daemon.tick_poller()
    assert calls[mark:] == [["ls-remote", "--", remote, "refs/heads/main"]]


def test_restart_reads_the_clone_when_the_sha_is_unchanged(tmp_path: Path):
    remote = _seed(tmp_path)
    first, _first_clock = _start(tmp_path, remote)
    first.tick_poller()
    assert first.store is not None and first.store.get(KEY) is not None
    first.stop()
    (tmp_path / "state" / "items.json").unlink()

    run, calls = _recording(tmp_path / "state" / "git-home")
    second, clock = _start(tmp_path, remote, git=run)
    assert second.api is not None and second.store is not None
    second.tick_poller()
    assert calls == [["ls-remote", "--", remote, "refs/heads/main"]]
    log = (tmp_path / "state" / "bridge.log").read_text(encoding="utf-8")
    assert "github-poller unchanged" in log
    row = json.loads(second.api.properties()["Bots"])[0]
    assert row["summary"] == "Example feed."
    assert row["state"] == "idle"
    assert row["last_seen"] == int(NOW.timestamp())
    item = second.store.get(KEY)
    assert item is not None
    assert item.updated_at == "2026-10-17T11:40:00+00:00"
    assert row["name"] == "primary"

    clock.current += timedelta(seconds=60)
    second.tick_poller()
    assert calls == [
        ["ls-remote", "--", remote, "refs/heads/main"],
        ["ls-remote", "--", remote, "refs/heads/main"],
    ]


def test_pull_on_change_rebases_a_local_commit(tmp_path: Path):
    remote = _seed(tmp_path)
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    clone = _clone(daemon)
    note = clone / "log" / "desktop" / "note.txt"
    note.parent.mkdir(parents=True)
    note.write_text("local\n", encoding="utf-8")
    _git(clone, "add", "log/desktop/note.txt")
    _git(clone, "commit", "-m", "local note")
    bare = _bare(remote)

    def writer(side: Path) -> None:
        payload = _feed("Ship the sample")
        payload["items"][0]["updated_at"] = "2026-10-17T11:50:00+00:00"
        _write_json(side / "feed" / "primary.json", payload)

    _push(tmp_path, bare, "bot feed", writer)
    mark = len(calls)
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert any(call[0] == "pull" for call in calls[mark:])
    assert daemon.store.get(KEY).title == "Ship the sample"
    assert daemon.state == "ok"
    subjects = _git(clone, "log", "--format=%s").stdout
    assert "local note" in subjects
    assert not (clone / ".git" / "rebase-merge").exists()
    assert not (clone / ".git" / "rebase-apply").exists()


def test_rebase_conflict_aborts_and_fails_closed(tmp_path: Path):
    remote = _seed(tmp_path)
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    clone = _clone(daemon)
    state = clone / "desktop" / "state.json"
    state.write_text('{"schema":"tetherbot/1","items":[{"key":"local"}]}\n', encoding="utf-8")
    _git(clone, "add", "desktop/state.json")
    _git(clone, "commit", "-m", "local state")

    def writer(side: Path) -> None:
        path = side / "desktop" / "state.json"
        path.write_text(
            '{"schema":"tetherbot/1","items":[{"key":"remote"}]}\n',
            encoding="utf-8",
        )

    _push(tmp_path, _bare(remote), "remote state", writer)
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.state == "failed_closed"
    assert daemon.reason == "rebase conflict"
    assert daemon.store.get(KEY) is not None
    assert not (clone / ".git" / "rebase-merge").exists()
    assert not (clone / ".git" / "rebase-apply").exists()
    mark = len(calls)
    clock.current += timedelta(days=1)
    daemon.tick_poller()
    assert calls[mark:] == []
    assert daemon.poller.status().state == "failed-closed"


def test_bad_json_keeps_items_and_marks_the_feed_stale(tmp_path: Path):
    remote = _seed(tmp_path)
    daemon, clock = _start(tmp_path, remote)
    daemon.tick_poller()

    def writer(side: Path) -> None:
        path = side / "feed" / "primary.json"
        path.write_text("{", encoding="utf-8")

    _push(tmp_path, _bare(remote), "break feed", writer)
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.store.get(KEY).title.startswith("Approve")
    assert daemon.poller.stale == ["feed/primary.json"]
    assert daemon.reason == "feed/primary.json is unreadable"
    assert daemon.state == "degraded"


def test_newer_schema_keeps_items_and_names_the_version(tmp_path: Path):
    remote = _seed(tmp_path)
    daemon, clock = _start(tmp_path, remote)
    daemon.tick_poller()

    def writer(side: Path) -> None:
        payload = _feed()
        payload["schema"] = "tetherbot/2"
        _write_json(side / "feed" / "primary.json", payload)

    _push(tmp_path, _bare(remote), "future schema", writer)
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.store.get(KEY) is not None
    assert daemon.poller.stale == ["feed/primary.json"]
    assert "unsupported schema tetherbot/2" in daemon.reason
    assert "update tetherbot" in daemon.reason


def test_bad_desktop_state_does_not_wipe_feed_items(tmp_path: Path):
    remote = _seed(tmp_path)
    daemon, clock = _start(tmp_path, remote)
    daemon.tick_poller()

    def writer(side: Path) -> None:
        _write_json(side / "desktop" / "state.json", {"schema": "tetherbot/2", "items": []})

    _push(tmp_path, _bare(remote), "future state", writer)
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.store.get(KEY) is not None
    assert "desktop/state.json" in daemon.poller.stale
    assert "unsupported schema tetherbot/2" in daemon.reason


def test_https_ssh_and_userinfo_do_not_run_git(tmp_path: Path):
    def explode(args, cwd):
        raise AssertionError((args, cwd))

    https, _clock = _start(
        tmp_path,
        "https://github.com/owner/repo.git",
        git=explode,
        credential_helper="",
    )
    assert https.reason == "credential helper is not installed"
    https.tick_poller()
    assert https.poller.status().state == "degraded"

    ssh_dir = tmp_path / "ssh"
    ssh_dir.mkdir()
    ssh, _clock = _start(
        ssh_dir,
        "git@github.com:owner/repo.git",
        auth="ssh-deploy-key",
        git=explode,
    )
    assert ssh.reason == "deploy key is not configured"

    poller = GitHubPoller(git=explode)
    poller.start(_ctx(tmp_path / "userinfo", "https://user:token@github.com/owner/repo.git"))
    poller.tick()
    assert poller.overlay == ("degraded", "remote must not contain credentials")


def test_offline_skips_git_until_the_link_returns(tmp_path: Path):
    remote = _seed(tmp_path)
    up = {"value": False}
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, _clock = _start(tmp_path, remote, git=run, online=lambda: up["value"])
    daemon.tick_poller()
    assert calls == []
    assert daemon.state == "offline"
    assert daemon.reason == "offline"
    up["value"] = True
    daemon.tick_poller()
    assert calls
    assert daemon.store.get(KEY) is not None
    assert daemon.state == "ok"


def test_screen_lock_stretches_the_interval(tmp_path: Path):
    remote = _seed(tmp_path)
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run, locked=lambda: True)
    daemon.tick_poller()
    mark = len(calls)
    clock.current += timedelta(seconds=120)
    daemon.tick_poller()
    assert len(calls) == mark
    clock.current += timedelta(seconds=480)
    daemon.tick_poller()
    assert calls[mark:] == [["ls-remote", "--", remote, "refs/heads/main"]]


def test_webhook_burst_polls_early(tmp_path: Path):
    remote = _seed(tmp_path)
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    mark = len(calls)
    moment = NOW + timedelta(seconds=30)
    clock.current = moment
    daemon.webhook = type("Burst", (), {"poll_burst": (moment,)})()
    daemon.tick_poller()
    assert calls[mark:] == [["ls-remote", "--", remote, "refs/heads/main"]]
    assert daemon.webhook.poll_burst == ()


def test_push_retries_twice_then_succeeds(tmp_path: Path):
    script = ScriptedGit(pushes=3)
    remote = (tmp_path / "repo.git").resolve().as_uri()
    clone = tmp_path / "repos" / "repo"
    (clone / ".git").mkdir(parents=True)
    (clone / "desktop").mkdir(parents=True)
    (clone / "desktop" / "state.json").write_text("{}\n", encoding="utf-8")
    poller = GitHubPoller(git=script)
    poller.start(_ctx(tmp_path, remote))
    assert poller.commit_paths(["desktop/state.json"]) is True
    assert script.names == ["status", "add", "commit", "push", "pull", "push", "pull", "push"]


def test_three_rejected_pushes_stay_degraded(tmp_path: Path):
    script = ScriptedGit(pushes=99)
    remote = (tmp_path / "repo.git").resolve().as_uri()
    clone = tmp_path / "repos" / "repo"
    (clone / ".git").mkdir(parents=True)
    (clone / "desktop").mkdir(parents=True)
    (clone / "desktop" / "state.json").write_text("{}\n", encoding="utf-8")
    poller = GitHubPoller(git=script)
    poller.start(_ctx(tmp_path, remote))
    assert poller.commit_paths(["desktop/state.json"]) is False
    assert poller.overlay == ("degraded", "push rejected")
    assert poller._closed is False
    assert script.names.count("push") == 3
    assert script.names.count("pull") == 2


def test_rejected_push_does_not_delay_the_next_poll(tmp_path: Path):
    repo = tmp_path / "repo"
    _git(None, "init", "-b", "main", str(repo))
    _git(repo, "config", "receive.denyCurrentBranch", "refuse")
    _write_json(repo / "feed" / "primary.json", _feed())
    _git(repo, "add", "feed/primary.json")
    _git(repo, "commit", "-m", "seed feed")
    remote = repo.resolve().as_uri()
    run, calls = _recording(tmp_path / "state" / "git-home")
    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    assert daemon.reason == "push rejected"
    assert daemon.poller._backoff == 0
    assert daemon.poller.next_poll() == int((clock.current + timedelta(seconds=60)).timestamp())

    def poll_once() -> None:
        clock.current += timedelta(seconds=60)
        mark = len(calls)
        daemon.tick_poller()
        assert calls[mark][0] == "ls-remote"
        assert daemon.poller._backoff == 0
        assert daemon.poller.next_poll() == int((clock.current + timedelta(seconds=60)).timestamp())

    poll_once()
    payload = _feed("Ship the sample")
    payload["items"][0]["updated_at"] = "2026-10-17T11:50:00+00:00"
    _write_json(repo / "feed" / "primary.json", payload)
    _git(repo, "add", "feed/primary.json")
    _git(repo, "commit", "-m", "retitle")
    poll_once()
    assert daemon.store.get(KEY).title == "Ship the sample"

    broken = _feed("Ship the sample")
    broken["schema"] = "tetherbot/2"
    broken["items"][0]["updated_at"] = "2026-10-17T11:55:00+00:00"
    _write_json(repo / "feed" / "primary.json", broken)
    _git(repo, "add", "feed/primary.json")
    _git(repo, "commit", "-m", "future schema")
    poll_once()
    assert daemon.store.get(KEY).title == "Ship the sample"
    assert "unsupported schema tetherbot/2" in daemon.reason
    assert daemon.poller.stale == ["feed/primary.json"]

    fixed = _feed("Recovered sample")
    fixed["items"][0]["updated_at"] = "2026-10-17T12:10:00+00:00"
    _write_json(repo / "feed" / "primary.json", fixed)
    _git(repo, "add", "feed/primary.json")
    _git(repo, "commit", "-m", "schema restored")
    poll_once()
    assert daemon.store.get(KEY).title == "Recovered sample"
    assert daemon.poller.stale == []
    assert daemon.poller._backoff == 0


def test_ls_remote_failure_still_backs_off(tmp_path: Path):
    remote = (tmp_path / "missing.git").resolve().as_uri()

    def run(args: list[str], cwd: Path | None) -> GitResult:
        del args, cwd
        return GitResult(1, "", "ls-remote failed")

    daemon, clock = _start(tmp_path, remote, git=run)
    daemon.tick_poller()
    assert daemon.poller.next_poll() == int((clock.current + timedelta(seconds=60)).timestamp())
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.poller.next_poll() == int((clock.current + timedelta(seconds=120)).timestamp())
    mark_next = daemon.poller.next_poll()
    clock.current += timedelta(seconds=60)
    daemon.tick_poller()
    assert daemon.poller.next_poll() == mark_next


def test_import_does_not_load_gi():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import sys, tetherbot.adapters.github_poller\n"
        "bad = [name for name in sys.modules if name.startswith('gi')]\n"
        "raise SystemExit(0 if not bad else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env, timeout=30)


def _bridge_log(daemon: BridgeDaemon) -> str:
    stream = daemon._log_stream.getvalue() if daemon._log_stream is not None else ""
    path = daemon.state_dir / "bridge.log"
    filed = path.read_text(encoding="utf-8") if path.is_file() else ""
    return stream + filed


def test_ls_remote_auth_failure_is_logged_without_git_output(tmp_path: Path):
    token = "ghp_" + ("e" * 36)
    leaked = (
        "fatal: Authentication failed for 'https://github.com/owner/repo.git/'\n"
        f"password={token}\n"
    )

    def run(args: list[str], cwd: Path | None) -> GitResult:
        del args, cwd
        return GitResult(1, f"stdout {token}", leaked)

    daemon, _clock = _start(
        tmp_path,
        "https://github.com/owner/repo.git",
        git=run,
        auth="https-token",
        credential_helper="/opt/tetherbot/git-credential-tetherbot",
    )
    daemon.tick_poller()
    logged = _bridge_log(daemon)
    assert daemon.poller.last_error == "ls-remote failed: auth"
    assert daemon.poller.overlay == ("degraded", "ls-remote failed: auth")
    assert "github-poller ls-remote failed: auth" in logged
    assert token not in logged
    assert "password=" not in logged
    assert "Authentication failed" not in logged
    assert "owner/repo" not in logged


def test_ls_remote_network_failure_names_network_only(tmp_path: Path):
    detail = "fatal: unable to access 'https://github.com/owner/repo.git/': Could not resolve host"

    def run(args: list[str], cwd: Path | None) -> GitResult:
        del args, cwd
        return GitResult(1, "", detail)

    daemon, _clock = _start(
        tmp_path,
        "https://github.com/owner/repo.git",
        git=run,
        auth="https-token",
        credential_helper="/opt/tetherbot/git-credential-tetherbot",
    )
    daemon.tick_poller()
    logged = _bridge_log(daemon)
    assert daemon.poller.last_error == "ls-remote failed: network"
    assert "github-poller ls-remote failed: network" in logged
    assert "Could not resolve host" not in logged
    assert "owner/repo" not in logged


def _helper_seen(tmp_path: Path, monkeypatch, *, pass_bus: bool) -> dict[str, str]:
    real_home = tmp_path / "real-home"
    record = tmp_path / "helper-env.json"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    helper = bindir / "git-credential-tetherbot"
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        "from pathlib import Path\n"
        f"Path({str(record)!r}).write_text(json.dumps(dict(os.environ)), encoding='utf-8')\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    git = bindir / "git"
    git.write_text(f"#!/bin/sh\nexec {shlex.quote(str(helper))} \"$@\"\n", encoding="utf-8")
    git.chmod(0o755)
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("GH_TOKEN", "ghp_" + ("a" * 36))
    monkeypatch.setenv("TETHERBOT_LEAK", "should-not-pass")
    if pass_bus:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(real_home / "xdg-config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(real_home / "xdg-data"))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    else:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    result = SubprocessGit(tmp_path / "git-home").run(["ls-remote"], None)
    assert result.code == 0
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert "GH_TOKEN" not in seen
    assert "TETHERBOT_LEAK" not in seen
    assert "ghp_" not in record.read_text(encoding="utf-8")
    return seen


def test_subprocess_git_env_reaches_a_fake_helper(tmp_path: Path, monkeypatch):
    seen = _helper_seen(tmp_path, monkeypatch, pass_bus=True)
    real_home = tmp_path / "real-home"
    assert seen["XDG_CONFIG_HOME"] == str(real_home / "xdg-config")
    assert seen["XDG_DATA_HOME"] == str(real_home / "xdg-data")
    assert seen["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert seen["XDG_RUNTIME_DIR"] == str(tmp_path / "runtime")
    assert seen["HOME"] == str(tmp_path / "git-home")
    assert seen["GIT_CONFIG_GLOBAL"] == os.devnull
    assert seen["GIT_CONFIG_SYSTEM"] == os.devnull


def test_subprocess_git_env_defaults_xdg_and_omits_an_unset_bus(tmp_path: Path, monkeypatch):
    seen = _helper_seen(tmp_path, monkeypatch, pass_bus=False)
    real_home = tmp_path / "real-home"
    assert seen["XDG_CONFIG_HOME"] == str(real_home / ".config")
    assert seen["XDG_DATA_HOME"] == str(real_home / ".local" / "share")
    assert "DBUS_SESSION_BUS_ADDRESS" not in seen
    assert "XDG_RUNTIME_DIR" not in seen
    assert seen["HOME"] == str(tmp_path / "git-home")
    assert seen["GIT_CONFIG_GLOBAL"] == os.devnull


def test_secret_shaped_git_args_do_not_spawn(tmp_path: Path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError((args, kwargs))

    monkeypatch.setattr("tetherbot.adapters.github_poller.subprocess.run", explode)
    result = SubprocessGit(tmp_path).run(
        ["clone", "--", "https://ghp_abcdefghijklmnopqrstuvwxyz@github.com/o/r.git"],
        None,
    )
    assert result.code == 1
    assert result.stdout == ""


def test_https_runs_git_with_the_helper_and_not_the_token(tmp_path: Path):
    token = "ghp_" + ("b" * 36)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path | None) -> GitResult:
        del cwd
        calls.append(list(args))
        assert token not in " ".join(args)
        return GitResult(1, "", "")

    helper = "/opt/tetherbot/git-credential-tetherbot"
    daemon, _clock = _start(
        tmp_path,
        "https://github.com/owner/repo.git",
        git=run,
        auth="https-token",
        credential_helper=helper,
    )
    daemon.tick_poller()
    assert calls
    flat = " ".join(calls[0])
    assert "ls-remote" in flat
    assert "credential.helper=" in flat
    assert f"credential.helper={helper} --slot github-token" in flat
    assert "credential.useHttpPath=true" in flat
    assert "https://github.com/owner/repo.git" in flat
    assert "@" not in flat
    assert token not in flat
    assert daemon.poller.last_error == "ls-remote failed: network"


def test_https_clone_config_scopes_the_helper_and_omits_the_token(tmp_path: Path):
    token = "ghp_" + ("d" * 36)
    clone = tmp_path / "clone"
    _git(None, "init", "-b", "main", str(clone))
    helper = "/opt/tetherbot/git-credential-tetherbot"
    git = SubprocessGit(tmp_path / "git-home")
    assert configure_https_credentials(git, clone, helper) is True
    text = (clone / ".git" / "config").read_text(encoding="utf-8")
    assert token not in text
    assert helper in text
    assert "useHttpPath" in text
    listed = git.run(["config", "--local", "--get-all", "credential.helper"], clone)
    assert listed.code == 0
    values = listed.stdout.splitlines()
    assert "" in values
    assert f"{helper} --slot github-token" in values
    assert all(token not in value for value in values)


def test_template_feed_and_state_pass_the_schema_gate():
    feed = ROOT / "template-repo" / "feed" / "primary.json"
    state = ROOT / "template-repo" / "desktop" / "state.json"
    from tetherbot.adapters.github_poller import _read_feed, _read_state

    items, problem, view = _read_feed(feed, "feed/primary.json")
    assert problem is None
    assert view is not None and view.summary == "1 open ask."
    assert view.state == "needs_you"
    assert items and items[0].bot == "primary"
    assert _read_state(state) is None

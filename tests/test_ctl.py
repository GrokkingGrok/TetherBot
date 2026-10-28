# SPDX-License-Identifier: GPL-2.0-or-later
"""tetherbotctl: status, enable, secret set, and a webhook ping."""

import json
import os
import subprocess
import sys
import urllib.error
from io import StringIO
from pathlib import Path

import pytest

from tetherbot.config import load_config
from tetherbot.ctl import CtlContext, CtlError, _NoRedirect, main, post_ping, resume_parked_ids
from tetherbot.secrets import MemoryBackend, SecretStore

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "data" / "config.example.toml"
WEBHOOK_URL = "https://example.test/hook/primary"
WEBHOOK_KEY = "desk-hook-key"
GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz"


def test_status_of_a_missing_config_is_unconfigured(tmp_path: Path):
    context = _context(tmp_path)
    assert main(["status"], context) == 0
    lines = _out(context)
    assert lines[0] == "unconfigured"
    assert "reason: config.toml is missing" in lines
    assert "running: no" in lines
    assert not any(line.startswith("mode:") for line in lines)
    assert list(tmp_path.iterdir()) == []


def test_status_with_nothing_enabled(tmp_path: Path):
    path = _write_example(tmp_path)
    context = _context(tmp_path, config_path=path)
    assert main(["status"], context) == 0
    lines = _out(context)
    assert lines[0] == "unconfigured"
    assert "reason: no adapter is enabled" in lines
    assert "mode: webhook-only" in lines
    assert "running: no" in lines


def test_status_of_a_refused_config_does_not_print_the_secret(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'schema = "tetherbot/1"\nnote = "{GITHUB_TOKEN}"\n',
        encoding="utf-8",
    )
    context = _context(tmp_path, config_path=path)
    assert main(["status"], context) == 0
    text = context.stdout.getvalue() + context.stderr.getvalue()
    assert text.splitlines()[0] == "failed_closed"
    assert "looks like a secret" in text
    assert GITHUB_TOKEN not in text
    assert "running: no" in text


def test_status_uses_the_running_bridge():
    context = _context(
        Path("/unused"),
        properties=lambda: {
            "state": "degraded",
            "reason": "not started: webhook-sender",
            "mode": "full",
            "queue": 2,
        },
    )
    assert main(["status"], context) == 0
    lines = _out(context)
    assert lines[0] == "degraded"
    assert "reason: not started: webhook-sender" in lines
    assert "mode: full" in lines
    assert "queue: 2" in lines
    assert "running: yes" in lines
    assert not any(line.startswith("parked:") for line in lines)


def test_status_counts_pending_and_parked_separately():
    context = _context(
        Path("/unused"),
        properties=lambda: {
            "state": "degraded",
            "reason": "re-paste key",
            "mode": "full",
            "queue": 0,
        },
        queue=lambda: [
            {"action_id": "a-1", "state": "parked"},
            {"action_id": "a-2", "state": "pending"},
        ],
    )
    assert main(["status"], context) == 0
    lines = _out(context)
    assert "queue: 0" in lines
    assert "parked: 1" in lines
    assert lines[0] == "degraded"


def test_enable_rewrites_only_the_named_adapter(tmp_path: Path):
    path = _write_example(tmp_path)
    context = _context(tmp_path, config_path=path, set_enabled=None)
    assert main(["enable", "webhook"], context) == 0
    assert context.stdout.getvalue() == "enabled webhook\n"
    config = load_config(path)
    assert config.adapters["webhook-sender"].enabled is True
    assert config.adapters["github-poller"].enabled is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert WEBHOOK_KEY not in path.read_text(encoding="utf-8")

    assert main(["disable", "webhook"], context) == 0
    assert load_config(path).adapters["webhook-sender"].enabled is False
    assert "disabled webhook" in context.stdout.getvalue()


def test_enable_on_a_running_bridge_does_not_rewrite_the_file(tmp_path: Path):
    path = _write_example(tmp_path)
    before = path.read_text(encoding="utf-8")
    calls: list[tuple[str, bool]] = []
    context = _context(
        tmp_path,
        config_path=path,
        set_enabled=lambda name, enabled: calls.append((name, enabled)),
    )
    assert main(["enable", "repo"], context) == 0
    assert main(["disable", "official"], context) == 0
    assert calls == [("github-poller", True), ("official", False)]
    assert path.read_text(encoding="utf-8") == before
    assert context.stdout.getvalue() == "enabled repo\ndisabled official\n"


def test_enable_without_a_config_fails(tmp_path: Path):
    context = _context(tmp_path, set_enabled=None)
    assert main(["enable", "webhook"], context) == 1
    assert context.stderr.getvalue().strip() == "config.toml is missing"


def test_secret_set_stores_a_webhook_without_printing_it(tmp_path: Path):
    prompts = iter((WEBHOOK_URL, WEBHOOK_KEY))
    seen: list[str] = []

    def prompt(label: str) -> str:
        seen.append(label)
        return next(prompts)

    context = _context(tmp_path, prompt=prompt)
    assert main(["secret", "set", "primary-actions"], context) == 0
    stored = context.secrets.get_webhook("primary-actions")
    assert stored is not None
    assert stored.url == WEBHOOK_URL
    assert stored.key == WEBHOOK_KEY
    assert seen == ["Webhook URL: ", "Webhook key: "]
    text = context.stdout.getvalue() + context.stderr.getvalue()
    assert text == "stored primary-actions\n"
    assert WEBHOOK_URL not in text
    assert WEBHOOK_KEY not in text
    assert list(tmp_path.iterdir()) == []


def test_resume_parked_ids_follow_the_slot():
    bots = {"primary": "primary-actions", "other": "other-actions"}
    rows = [
        {"action_id": "a-1", "bot": "primary", "state": "parked"},
        {"action_id": "a-2", "bot": "primary", "state": "pending"},
        {"action_id": "a-3", "bot": "other", "state": "parked"},
    ]
    assert resume_parked_ids("primary-actions", bots, rows) == ["a-1"]


def test_secret_set_asks_the_bridge_to_resume(tmp_path: Path):
    answers = iter((WEBHOOK_URL, WEBHOOK_KEY))
    resumed: list[str] = []
    context = _context(tmp_path, prompt=lambda _label: next(answers), resume=resumed.append)
    assert main(["secret", "set", "primary-actions"], context) == 0
    assert resumed == ["primary-actions"]
    assert WEBHOOK_URL not in context.stdout.getvalue()
    assert WEBHOOK_KEY not in context.stderr.getvalue()


def test_secret_set_stores_a_github_token_without_printing_it(tmp_path: Path):
    seen: list[str] = []

    def prompt(label: str) -> str:
        seen.append(label)
        return GITHUB_TOKEN

    context = _context(tmp_path, prompt=prompt)
    assert main(["secret", "set", "github-token"], context) == 0
    assert context.secrets.get_github_token("github-token") == GITHUB_TOKEN
    assert seen == ["GitHub token: "]
    text = context.stdout.getvalue() + context.stderr.getvalue()
    assert text == "stored github-token\n"
    assert GITHUB_TOKEN not in text


def test_empty_token_is_refused_without_a_value(tmp_path: Path):
    context = _context(tmp_path, prompt=lambda _label: "")
    assert main(["secret", "set", "github-token"], context) == 1
    assert context.stderr.getvalue().strip() == "github token is empty"
    assert context.secrets.get_github_token("github-token") is None
    assert context.stdout.getvalue() == ""


def test_insecure_webhook_url_is_refused_without_echo(tmp_path: Path):
    answers = iter(("http://example.test/hook", WEBHOOK_KEY))
    context = _context(tmp_path, prompt=lambda _label: next(answers))
    assert main(["secret", "set", "primary-actions"], context) == 1
    message = context.stderr.getvalue()
    assert "https" in message
    assert "example.test" not in message
    assert WEBHOOK_KEY not in message
    assert context.secrets.get_webhook("primary-actions") is None


def test_webhook_test_prints_only_the_status(tmp_path: Path):
    path = _write_bot(tmp_path)
    seen: list[tuple[str, str]] = []

    def post(url: str, key: str) -> int:
        seen.append((url, key))
        return 200

    context = _context(tmp_path, config_path=path, post=post)
    context.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    assert main(["webhook", "test", "primary"], context) == 0
    assert context.stdout.getvalue() == "200\n"
    assert context.stderr.getvalue() == ""
    assert seen == [(WEBHOOK_URL, WEBHOOK_KEY)]
    assert WEBHOOK_URL not in context.stdout.getvalue()
    assert WEBHOOK_KEY not in context.stdout.getvalue()


def test_webhook_test_prints_an_error_status(tmp_path: Path):
    path = _write_bot(tmp_path)
    context = _context(tmp_path, config_path=path, post=lambda _url, _key: 401)
    context.secrets.put_webhook("primary-actions", WEBHOOK_URL, WEBHOOK_KEY)
    assert main(["webhook", "test", "primary"], context) == 0
    assert context.stdout.getvalue() == "401\n"
    assert WEBHOOK_URL not in context.stdout.getvalue()


def test_webhook_test_refuses_a_missing_config_bot_or_secret(tmp_path: Path):
    missing = _context(tmp_path)
    assert main(["webhook", "test", "primary"], missing) == 1
    assert missing.stderr.getvalue().strip() == "config.toml is missing"

    path = _write_example(tmp_path)
    unknown = _context(tmp_path, config_path=path)
    assert main(["webhook", "test", "primary"], unknown) == 1
    assert unknown.stderr.getvalue().strip() == "bot has no webhook slot"

    configured = _write_bot(tmp_path)
    empty = _context(tmp_path, config_path=configured)
    assert main(["webhook", "test", "primary"], empty) == 1
    assert empty.stderr.getvalue().strip() == "webhook secret is not stored"
    assert WEBHOOK_URL not in empty.stderr.getvalue()


def test_post_ping_rejects_a_non_https_url_before_opening_a_socket():
    def open_request(*_args, **_kwargs):
        raise AssertionError("opened a socket")

    opener = _Opener(open_request)
    with pytest.raises(CtlError, match="https"):
        post_ping("http://example.test/hook", WEBHOOK_KEY, opener=opener)
    with pytest.raises(CtlError, match="https"):
        post_ping("https://user:pw@example.test/hook", WEBHOOK_KEY, opener=opener)
    assert opener.calls == 0


def test_post_ping_sends_a_bearer_ping_and_returns_the_status():
    opener = _Opener(lambda request, timeout: _response(204, request, timeout))
    assert post_ping(WEBHOOK_URL, WEBHOOK_KEY, opener=opener) == 204
    request, timeout = opener.seen
    assert timeout == 30
    assert request.get_method() == "POST"
    payload = json.loads(request.data)
    assert payload["schema"] == "tetherbot/1"
    assert payload["type"] == "ping"
    assert payload["client"] == {"host": "desktop", "name": "tetherbot", "version": "0.1.0"}
    assert payload["sent_at"]
    assert WEBHOOK_KEY.encode() not in request.data
    assert WEBHOOK_URL.encode() not in request.data
    assert request.get_header("Authorization") == f"Bearer {WEBHOOK_KEY}"
    assert request.get_header("Content-type") == "application/json"


def test_post_ping_returns_an_http_error_code():
    error = urllib.error.HTTPError(WEBHOOK_URL, 401, "no", None, None)

    def open_request(_request: object, _timeout: object) -> object:
        raise error

    assert post_ping(WEBHOOK_URL, WEBHOOK_KEY, opener=_Opener(open_request)) == 401


def test_post_ping_hides_the_url_when_the_request_fails():
    def open_request(_request: object, _timeout: object) -> object:
        raise urllib.error.URLError(WEBHOOK_URL)

    with pytest.raises(CtlError, match="webhook test failed") as caught:
        post_ping(WEBHOOK_URL, WEBHOOK_KEY, opener=_Opener(open_request))
    assert WEBHOOK_URL not in str(caught.value)
    assert WEBHOOK_KEY not in str(caught.value)
    assert caught.value.__cause__ is None


def test_redirect_is_not_followed():
    assert _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.test") is None


def test_help_and_usage_do_not_need_a_context(capsys: pytest.CaptureFixture[str]):
    assert main(["--help"]) == 0
    assert "webhook" in capsys.readouterr().out
    assert main(["webhook", "test", "--help"]) == 0
    assert "tetherbotctl webhook test" in capsys.readouterr().out
    assert main(["enable", "nope"]) == 2
    assert main(["secret"]) == 2
    assert main([]) == 2


def test_cancelled_prompt(tmp_path: Path):
    def prompt(_label: str) -> str:
        raise KeyboardInterrupt

    context = _context(tmp_path, prompt=prompt)
    assert main(["secret", "set", "github-token"], context) == 1
    assert context.stderr.getvalue().strip() == "cancelled"


def test_clipboard_debug_prints_types_and_not_the_text(tmp_path: Path):
    secret = "aB3!xxxx"
    state = tmp_path / "state"
    state.mkdir()
    (state / "clipboard.json").write_text(
        json.dumps(
            {
                "kind": "clipboard",
                "entries": [{"id": "c-1234abcd", "text": secret, "at": 1}],
                "last_offer": {
                    "at": 1,
                    "mimes": ["text/plain", "UTF8_STRING", "chromium/x-source-url"],
                    "result": "skipped-lookalike",
                    "wm_class": "google-chrome",
                    "text": secret,
                },
            }
        ),
        encoding="utf-8",
    )
    context = _context(tmp_path, state_dir=state)
    assert main(["clipboard-debug"], context) == 0
    output = context.stdout.getvalue()
    assert "result: skipped-lookalike" in output
    assert "reason: password lookalike" in output
    assert "text/plain" in output
    assert "UTF8_STRING" in output
    assert "chromium/x-source-url" in output
    assert "wm_class: google-chrome" in output
    assert secret not in output
    assert "entries" not in output
    missing = _context(tmp_path, state_dir=tmp_path / "empty")
    assert main(["clipboard-debug"], missing) == 0
    assert "result: none" in missing.stdout.getvalue()
    assert secret not in missing.stdout.getvalue()


def test_window_faults_prints_the_log_and_skips_clipboard_text(tmp_path: Path):
    secret = "ghp_notarealtoken"
    state = tmp_path / "state"
    state.mkdir()
    (state / "clipboard.json").write_text(
        json.dumps({"entries": [{"id": "c-1234abcd", "text": secret}]}),
        encoding="utf-8",
    )
    (state / "window-faults.log").write_text("Fatal Python error: Aborted\n", encoding="utf-8")
    context = _context(tmp_path, state_dir=state)
    assert main(["window-faults"], context) == 0
    output = context.stdout.getvalue()
    assert "Fatal Python error: Aborted" in output
    assert secret not in output
    missing = _context(tmp_path, state_dir=tmp_path / "empty")
    assert main(["window-faults"], missing) == 0
    assert missing.stdout.getvalue() == ""


def test_import_does_not_load_gi():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "bridge")
    code = (
        "import sys, tetherbot.ctl\n"
        "bad = [name for name in sys.modules if name == 'gi' or name.startswith('gi.')]\n"
        "raise SystemExit(0 if not bad else 1)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env, timeout=20)


def _context(tmp_path: Path, **overrides: object) -> CtlContext:
    values: dict[str, object] = {
        "config_path": tmp_path / "config.toml",
        "stdout": StringIO(),
        "stderr": StringIO(),
        "prompt": lambda _label: "",
        "secrets": SecretStore(MemoryBackend()),
        "properties": lambda: None,
        "set_enabled": None,
        "post": lambda _url, _key: 200,
    }
    values.update(overrides)
    return CtlContext(**values)  # type: ignore[arg-type]


def _write_example(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _write_bot(tmp_path: Path) -> Path:
    path = tmp_path / "bot.toml"
    path.write_text(
        "\n".join(
            [
                'schema = "tetherbot/1"',
                "[bridge]",
                'mode = "webhook-only"',
                "[bots.primary]",
                'webhook_slot = "primary-actions"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _out(context: CtlContext) -> list[str]:
    return context.stdout.getvalue().splitlines()


class _Opener:
    def __init__(self, open_request):
        self._open_request = open_request
        self.calls = 0
        self.seen = None

    def open(self, request, timeout=None):
        self.calls += 1
        self.seen = (request, timeout)
        return self._open_request(request, timeout)


class _Response:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _response(status: int, _request: object, _timeout: object) -> _Response:
    return _Response(status)

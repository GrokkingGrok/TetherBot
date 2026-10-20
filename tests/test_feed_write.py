# SPDX-License-Identifier: GPL-2.0-or-later
"""Bot-side feed writer, with a fake contents API and no network."""

import base64
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("feed_write", _ROOT / "tools" / "feed_write.py")
assert _SPEC is not None and _SPEC.loader is not None
feed_write = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(feed_write)

TOKEN = "test-token"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
PATH = "feed/primary.json"
URL = "https://api.github.com/repos/owner/name/contents/feed/primary.json"


class FakeGitHub:
    """In-memory contents API. Records every URL and never opens a socket."""

    def __init__(self) -> None:
        self.docs: dict[str, str] = {}
        self.shas: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.conflicts_left = 0
        self.conflict_status = 409
        self.forced: dict[str, int] = {}
        self.on_conflict = None
        self.last_message = ""

    def seed(self, doc: dict, sha: str = "sha-1", path: str = PATH) -> None:
        self.docs[path] = feed_write.dumps_feed(doc)
        self.shas[path] = sha

    def document(self, path: str = PATH) -> dict:
        return json.loads(self.docs[path])

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        assert "?" not in url
        assert TOKEN not in url
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert url.startswith("https://api.github.com/repos/owner/name/contents/")
        path = url.split("/contents/", 1)[1]
        assert path.startswith("feed/")
        assert "desktop" not in path
        forced = self.forced.get(method)
        if forced:
            return forced, {}, b""
        if method == "GET":
            if path not in self.docs:
                return 404, {}, b'{"message":"Not Found"}'
            payload = {
                "sha": self.shas[path],
                "encoding": "base64",
                "content": base64.b64encode(self.docs[path].encode()).decode(),
            }
            return 200, {}, json.dumps(payload).encode()
        if method == "PUT":
            data = json.loads(body)
            self.last_message = data["message"]
            assert TOKEN not in data["message"]
            if self.conflicts_left > 0:
                self.conflicts_left -= 1
                if self.on_conflict is not None:
                    self.on_conflict(path)
                else:
                    self.shas[path] = self.shas.get(path, "sha") + "x"
                return self.conflict_status, {}, b"{}"
            expected = self.shas.get(path)
            if expected is not None and data.get("sha") != expected:
                return 409, {}, b"{}"
            if expected is None and "sha" in data:
                return 422, {}, b"{}"
            text = base64.b64decode(data["content"]).decode()
            self.docs[path] = text
            self.shas[path] = f"sha-{len(self.calls)}"
            return (201 if expected is None else 200), {}, b"{}"
        raise AssertionError(method)


def _feed(items: list[dict], status: dict | None = None) -> dict:
    doc = {
        "schema": "tetherbot/1",
        "bot": "primary",
        "updated_at": "2026-10-17T11:00:00+00:00",
        "items": items,
    }
    if status is not None:
        doc["status"] = status
    return doc


def _todo(
    item_id: str,
    title: str,
    *,
    body: str | None = None,
    status: str = "open",
    kind: str = "todo",
) -> dict:
    item = {
        "id": item_id,
        "kind": kind,
        "title": title,
        "status": status,
        "created": "2026-10-17T11:00:00+00:00",
        "updated_at": "2026-10-17T11:00:00+00:00",
        "actions": ["done"] if kind == "todo" else ["approve", "veto"],
        "notify": True,
        "source": {"bot": "primary"},
    }
    if body is not None:
        item["body"] = body
    return item


def _run(fake: FakeGitHub, *args: str, env: dict | None = None) -> int:
    environ = {"TETHERBOT_FEED_TOKEN": TOKEN}
    if env is not None:
        environ = env
    return feed_write.main(
        ["--repo", "owner/name", "--bot", "primary", *args],
        request=fake,
        now=NOW,
        environ=environ,
    )


def _puts(fake: FakeGitHub) -> list[tuple]:
    return [call for call in fake.calls if call[0] == "PUT"]


def test_add_todo_creates_the_feed_file(capsys):
    fake = FakeGitHub()
    code = _run(fake, "add-todo", "--title", "Send the note", "--body", "Example text only.")
    assert code == 0
    assert len(_puts(fake)) == 1
    assert [call[1] for call in fake.calls] == [URL, URL]
    doc = fake.document()
    item = doc["items"][0]
    assert item["id"] == "primary-20261017-01"
    assert item["kind"] == "todo"
    assert item["status"] == "open"
    assert item["actions"] == ["done"]
    assert item["notify"] is True
    assert item["source"] == {"bot": "primary"}
    assert item["created"] == "2026-10-17T12:00:00+00:00"
    assert doc["updated_at"] == item["updated_at"]
    assert "key" not in item
    printed = json.loads(capsys.readouterr().out)
    assert printed["key"] == "primary/primary-20261017-01"
    assert fake.last_message == "Add todo primary-20261017-01: Send the note"
    assert TOKEN not in fake.docs[PATH]


def test_add_todo_due_and_todo_kind():
    fake = FakeGitHub()
    code = _run(
        fake,
        "add-todo",
        "--title", "Pay the bill",
        "--due", "2026-10-18T15:30:00-07:00",
        "--todo-kind", "bill",
    )
    assert code == 0
    item = fake.document()["items"][0]
    assert item["due"] == "2026-10-18 15:30"
    assert item["todo_kind"] == "bill"


def test_add_ask_actions():
    fake = FakeGitHub()
    assert _run(fake, "add-ask", "--title", "Approve the sample request or turn it down") == 0
    item = fake.document()["items"][0]
    assert item["kind"] == "ask"
    assert item["actions"] == ["approve", "veto"]
    assert item["id"] == "primary-20261017-01"


def test_idempotent_open_todo_is_not_duplicated(capsys):
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note", body="Example text only.")]))
    code = _run(fake, "add-todo", "--title", "Send the note", "--body", "Example text only.")
    assert code == 0
    assert _puts(fake) == []
    assert len(fake.document()["items"]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["key"] == "primary/primary-20261017-01"


def test_same_title_on_a_done_item_is_a_new_todo():
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note", status="done")]))
    assert _run(fake, "add-todo", "--title", "Send the note") == 0
    items = fake.document()["items"]
    assert [item["id"] for item in items] == ["primary-20261017-01", "primary-20261017-02"]
    assert items[1]["status"] == "open"


def test_close_reopen_and_drop():
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note")]))
    assert _run(fake, "close", "--key", "primary/primary-20261017-01") == 0
    item = fake.document()["items"][0]
    assert item["status"] == "done"
    assert item["updated_at"] == "2026-10-17T12:00:00+00:00"
    assert item["created"] == "2026-10-17T11:00:00+00:00"
    assert fake.document()["updated_at"] == "2026-10-17T12:00:00+00:00"
    puts = len(_puts(fake))
    assert _run(fake, "close", "--key", "primary-20261017-01") == 0
    assert len(_puts(fake)) == puts
    assert _run(fake, "reopen", "--key", "primary-20261017-01") == 0
    assert fake.document()["items"][0]["status"] == "open"
    assert _run(fake, "close", "--key", "primary-20261017-01", "--status", "dropped") == 0
    assert fake.document()["items"][0]["status"] == "dropped"
    assert fake.last_message == "Drop primary-20261017-01"


def test_missing_item_exits_not_found(capsys):
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note")]))
    code = _run(fake, "close", "--key", "primary/missing-01")
    assert code == 3
    assert _puts(fake) == []
    assert "was not found" in capsys.readouterr().err


def test_conflict_retries_then_reapplies():
    fake = FakeGitHub()
    fake.seed(_feed([_todo("other-01", "Keep this note")]))
    fake.conflicts_left = 1

    def collide(path: str) -> None:
        doc = json.loads(fake.docs[path])
        doc["items"].append(_todo("concurrent-01", "Added while we wrote"))
        doc["updated_at"] = "2026-10-17T12:05:00+00:00"
        fake.docs[path] = feed_write.dumps_feed(doc)
        fake.shas[path] = "sha-concurrent"

    fake.on_conflict = collide
    assert _run(fake, "add-todo", "--title", "Send the note") == 0
    assert len(_puts(fake)) == 2
    ids = [item["id"] for item in fake.document()["items"]]
    assert ids == ["other-01", "concurrent-01", "primary-20261017-01"]
    assert fake.calls[-1][3] and b"sha-concurrent" in fake.calls[-1][3]


def test_conflict_status_422_is_retried():
    fake = FakeGitHub()
    fake.conflicts_left = 1
    fake.conflict_status = 422
    fake.seed(_feed([]))
    assert _run(fake, "add-todo", "--title", "Send the note") == 0
    assert len(_puts(fake)) == 2
    assert fake.document()["items"][0]["title"] == "Send the note"


def test_conflict_retries_exhausted(capsys):
    fake = FakeGitHub()
    fake.conflicts_left = 4
    fake.seed(_feed([_todo("other-01", "Keep this note")]))
    code = _run(fake, "add-todo", "--title", "Send the note")
    assert code == 4
    assert len(_puts(fake)) == 4
    assert [item["id"] for item in fake.document()["items"]] == ["other-01"]
    err = capsys.readouterr().err
    assert "3 retries" in err
    assert err.count("\n") == 1
    assert all("desktop" not in call[1] for call in fake.calls)


def test_secret_guard_rejects_without_writing(capsys):
    fake = FakeGitHub()
    secret = "ghp_" + ("a" * 20)
    code = _run(fake, "add-todo", "--title", secret)
    assert code == 1
    assert _puts(fake) == []
    err = capsys.readouterr().err
    assert "title looks like a secret" in err
    assert secret not in err
    assert "ghp_" not in err

    fake = FakeGitHub()
    code = _run(fake, "add-todo", "--title", "Send the note", "--body", "account 123456789")
    assert code == 1
    assert fake.docs == {}
    err = capsys.readouterr().err
    assert "body looks like a secret" in err
    assert "123456789" not in err

    fake = FakeGitHub()
    code = _run(fake, "status", "--state", "error", "--summary", "sk-" + ("b" * 12))
    assert code == 1
    assert _puts(fake) == []
    err = capsys.readouterr().err
    assert "summary looks like a secret" in err
    assert "sk-" not in err


def test_auth_failure_is_one_line(capsys):
    for status in (401, 403):
        fake = FakeGitHub()
        fake.forced["GET"] = status
        code = _run(fake, "list")
        assert code == 2
        err = capsys.readouterr().err
        assert f"HTTP {status}" in err
        assert "expired" in err
        assert TOKEN not in err
        assert err.count("\n") == 1
        assert _puts(fake) == []


def test_desktop_paths_are_never_requested():
    fake = FakeGitHub()
    assert _run(fake, "add-todo", "--title", "Send the note") == 0
    assert _run(fake, "status", "--state", "idle", "--summary", "1 todo.") == 0
    assert fake.calls
    for _method, url, _headers, _body in fake.calls:
        assert url == URL
        assert "desktop" not in url
    for path in ("desktop/state.json", "desktop/machine.json", "log/desktop/2026-10.jsonl"):
        try:
            feed_write.assert_feed_path(path)
        except feed_write.FeedWriteError as exc:
            assert exc.code == 1
            assert "desktop" in str(exc)
        else:
            raise AssertionError(path)
    feed_write.assert_feed_path(PATH)


def test_dry_run_prints_the_file_without_putting(capsys):
    fake = FakeGitHub()
    code = _run(fake, "--dry-run", "add-todo", "--title", "Send the note")
    assert code == 0
    assert _puts(fake) == []
    printed = json.loads(capsys.readouterr().out)
    assert printed["items"][0]["title"] == "Send the note"
    assert "key" not in printed["items"][0]


def test_list_open_items(capsys):
    fake = FakeGitHub()
    fake.seed(
        _feed(
            [
                _todo("primary-20261017-01", "Send the note"),
                _todo("primary-20261017-02", "Already done", status="done"),
            ]
        )
    )
    assert _run(fake, "list", "--open") == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["key"] for row in rows] == ["primary/primary-20261017-01"]
    assert _puts(fake) == []


def test_status_bumps_the_file_and_leaves_items(capsys):
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note")]))
    code = _run(
        fake,
        "status",
        "--state", "idle",
        "--summary", "3 open todos.",
        "--last-run", "2026-10-17T11:00:00Z",
        "--next-run", "2026-10-18T12:00:00+00:00",
    )
    assert code == 0
    doc = fake.document()
    assert doc["updated_at"] == "2026-10-17T12:00:00+00:00"
    assert doc["items"][0]["updated_at"] == "2026-10-17T11:00:00+00:00"
    assert doc["status"]["summary"] == "3 open todos."
    assert doc["status"]["state"] == "idle"
    assert doc["status"]["last_run"] == "2026-10-17T11:00:00+00:00"
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"]["summary"] == "3 open todos."


def test_missing_token_and_bad_repo_do_not_call_github(capsys):
    fake = FakeGitHub()
    code = _run(fake, "list", env={})
    assert code == 1
    err = capsys.readouterr().err
    assert "TETHERBOT_FEED_TOKEN" in err
    assert fake.calls == []

    code = feed_write.main(
        ["--repo", "https://user:secret@github.com/owner/name", "list"],
        request=fake,
        now=NOW,
        environ={"TETHERBOT_FEED_TOKEN": TOKEN},
    )
    assert code == 1
    assert "owner/name" in capsys.readouterr().err
    assert "secret" not in capsys.readouterr().err
    assert fake.calls == []


def test_normalize_due_and_auto_id():
    assert feed_write.normalize_due("2026-10-18T00:00:00+00:00") == "2026-10-18"
    assert feed_write.normalize_due("2026-10-18") == "2026-10-18"
    assert feed_write.normalize_due("2026-10-19 09:30") == "2026-10-19 09:30"
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "First")]))
    assert _run(fake, "add-todo", "--title", "Second") == 0
    assert fake.document()["items"][1]["id"] == "primary-20261017-02"


def test_add_todo_tags_priority_owner_and_markdown(tmp_path):
    fake = FakeGitHub()
    body = tmp_path / "note.md"
    body.write_text("# Send the note\n\n- one\n", encoding="utf-8")
    code = _run(
        fake,
        "add-todo",
        "--title", "Send the note",
        "--body-file", str(body),
        "--tag", "home",
        "--tag", "errand",
        "--priority", "1",
        "--owner", "bot",
        "--waiting-on", "reply",
        "--due", "2026-10-20 10:00",
    )
    assert code == 0
    item = fake.document()["items"][0]
    assert item["body"] == "# Send the note\n\n- one"
    assert item["body_format"] == "markdown"
    assert item["tags"] == ["home", "errand"]
    assert item["priority"] == 1
    assert item["owner"] == "bot"
    assert item["waiting"] == {"on": "reply", "since": "2026-10-17"}
    assert item["due"] == "2026-10-20 10:00"
    assert _run(fake, "tag-color", "--tag", "home", "--color", "teal") == 0
    assert fake.document()["tag_colors"]["home"] == "teal"
    assert _run(
        fake,
        "edit",
        "--key", "primary/primary-20261017-01",
        "--add-tag", "bills",
        "--remove-tag", "errand",
        "--clear-waiting",
        "--priority", "2",
    ) == 0
    edited = fake.document()["items"][0]
    assert edited["tags"] == ["home", "bills"]
    assert "waiting" not in edited
    assert edited["priority"] == 2
    assert edited["updated_at"] == "2026-10-17T12:00:00+00:00"


def test_writer_rejects_a_secret_tag_and_keeps_desktop_untouched(capsys):
    fake = FakeGitHub()
    secret = "abcdef0123456789abcdef0123456789"
    code = _run(fake, "add-todo", "--title", "Send the note", "--tag", secret)
    assert code == 1
    assert _puts(fake) == []
    err = capsys.readouterr().err
    assert "tag looks like a secret" in err
    assert secret not in err
    assert all("desktop" not in call[1] for call in fake.calls)


def test_a_second_bot_writes_only_its_file(capsys):
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note")]))
    code = feed_write.main(
        ["--repo", "owner/name", "--bot", "notes", "add-todo", "--title", "Write the note"],
        request=fake,
        now=NOW,
        environ={"TETHERBOT_FEED_TOKEN": TOKEN},
    )
    assert code == 0
    notes = "feed/notes.json"
    assert notes in fake.docs
    doc = fake.document(notes)
    assert doc["bot"] == "notes"
    assert doc["items"][0]["source"] == {"bot": "notes"}
    assert doc["items"][0]["id"] == "notes-20261017-01"
    assert fake.document()["items"][0]["id"] == "primary-20261017-01"
    printed = json.loads(capsys.readouterr().out)
    assert printed["key"] == "notes/notes-20261017-01"
    assert all("desktop" not in call[1] for call in fake.calls)


def test_status_name_keeps_the_string_bot_id(capsys):
    fake = FakeGitHub()
    fake.seed(_feed([_todo("primary-20261017-01", "Send the note")]))
    code = _run(
        fake,
        "status",
        "--state", "idle",
        "--summary", "1 open todo.",
        "--name", "Primary",
    )
    assert code == 0
    doc = fake.document()
    assert doc["bot"] == "primary"
    assert doc["display_name"] == "Primary"
    assert doc["items"][0]["title"] == "Send the note"
    printed = json.loads(capsys.readouterr().out)
    assert printed["display_name"] == "Primary"


def test_put_404_is_not_found(capsys):
    fake = FakeGitHub()
    fake.forced["PUT"] = 404
    code = _run(fake, "add-todo", "--title", "Send the note")
    assert code == 3
    err = capsys.readouterr().err
    assert "HTTP 404" in err
    assert TOKEN not in err
    assert fake.docs == {}

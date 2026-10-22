# SPDX-License-Identifier: GPL-2.0-or-later
"""Queue persistence, coalescing, pacing, and the daily cap."""

from datetime import timedelta

import pytest

import tetherbot.files as files
from tests.helpers import NOW
from tetherbot.queue import ActionQueue, QueueError, queue_file_mode


def _enqueue(queue: ActionQueue, created: str, action_id: str, bot: str = "primary") -> str:
    return queue.enqueue(
        bot=bot,
        item=f"{bot}/sample-01",
        action="approve",
        created=created,
        action_id=action_id,
    )


def test_enqueue_fsyncs_and_resumes(tmp_path, monkeypatch):
    calls = {"fsync": 0}
    real = files.os.fsync

    def counting(fd: int) -> None:
        calls["fsync"] += 1
        real(fd)

    monkeypatch.setattr(files.os, "fsync", counting)
    queue = ActionQueue(tmp_path / "queue")
    action_id = _enqueue(queue, "2026-10-17T12:00:00+00:00", "a-example")
    path = tmp_path / "queue" / f"{action_id}.json"
    assert path.exists()
    assert queue_file_mode(path) == 0o600
    assert calls["fsync"] >= 2
    assert "secret" not in path.read_text(encoding="utf-8")
    resumed = ActionQueue(tmp_path / "queue")
    ready = resumed.next_batch(NOW + timedelta(seconds=20))
    assert ready is not None
    assert ready[0].action_id == action_id


def test_coalesce_quiet_period_and_maximum_wait(tmp_path):
    queue = ActionQueue(tmp_path / "queue")
    _enqueue(queue, "2026-10-17T12:00:00+00:00", "a-first")
    assert queue.next_batch(NOW) is None
    assert queue.next_batch(NOW + timedelta(seconds=19)) is None
    ready = queue.next_batch(NOW + timedelta(seconds=20))
    assert ready is not None and ready[0].action_id == "a-first"

    busy = ActionQueue(tmp_path / "busy")
    _enqueue(busy, "2026-10-17T12:00:00+00:00", "a-old")
    _enqueue(busy, "2026-10-17T12:01:50+00:00", "a-new")
    assert busy.next_batch(NOW + timedelta(seconds=110)) is None
    both = busy.next_batch(NOW + timedelta(seconds=120))
    assert both is not None
    assert [action.action_id for action in both] == ["a-old", "a-new"]


def test_pace_and_daily_cap(tmp_path):
    queue = ActionQueue(tmp_path / "queue", daily_cap=1)
    _enqueue(queue, "2026-10-17T12:00:00+00:00", "a-one")
    first = queue.next_batch(NOW + timedelta(seconds=20))
    assert first is not None
    queue.mark_attempt("primary", [first[0].action_id], now=NOW + timedelta(seconds=20))
    queue.accept([first[0].action_id])
    _enqueue(queue, "2026-10-17T12:00:20+00:00", "a-two")
    assert queue.next_batch(NOW + timedelta(seconds=80)) is None
    next_day = NOW + timedelta(days=1, seconds=20)
    later = queue.next_batch(next_day)
    assert later is not None
    assert later[0].action_id == "a-two"


def test_interval_blocks_a_second_post(tmp_path):
    queue = ActionQueue(tmp_path / "queue")
    _enqueue(queue, "2026-10-17T12:00:00+00:00", "a-one")
    first = queue.next_batch(NOW + timedelta(seconds=20))
    assert first is not None
    sent_at = NOW + timedelta(seconds=20)
    queue.mark_attempt("primary", [action.action_id for action in first], now=sent_at)
    queue.accept([action.action_id for action in first])
    _enqueue(queue, "2026-10-17T12:00:40+00:00", "a-two")
    assert queue.next_batch(NOW + timedelta(seconds=70)) is None
    ready = queue.next_batch(NOW + timedelta(seconds=80))
    assert ready is not None and ready[0].action_id == "a-two"


def test_secret_payload_is_not_written(tmp_path):
    queue = ActionQueue(tmp_path / "queue")
    with pytest.raises(QueueError, match="looks like a secret"):
        queue.enqueue(
            bot="primary",
            item="primary/sample-01",
            action="note",
            args={"text": "ghp_abcdefghijklmnopqrstuvwxyz"},
            created="2026-10-17T12:00:00+00:00",
            action_id="a-secret",
        )
    assert not (tmp_path / "queue" / "a-secret.json").exists()


def test_park_drop_and_retry(tmp_path):
    queue = ActionQueue(tmp_path / "queue")
    _enqueue(queue, "2026-10-17T12:00:00+00:00", "a-park")
    queue.park("a-park", "rejected_key")
    assert queue.next_batch(NOW + timedelta(seconds=20)) is None
    queue.retry("a-park")
    ready = queue.next_batch(NOW + timedelta(seconds=20))
    assert ready is not None
    queue.drop(ready[0].action_id)
    assert queue.next_batch(NOW + timedelta(seconds=20)) is None


def test_done_note_is_stored_and_a_blank_note_is_plain(tmp_path):
    queue = ActionQueue(tmp_path / "queue")
    queue.enqueue(
        bot="primary",
        item="primary/sample-01",
        action="done",
        args={"note": "  Packed the blue bag  "},
        created="2026-10-17T12:00:00+00:00",
        action_id="a-noted",
    )
    ready = queue.next_batch(NOW + timedelta(seconds=30))
    assert ready is not None
    assert ready[0].args == {"note": "Packed the blue bag"}
    queue.enqueue(
        bot="primary",
        item="primary/sample-02",
        action="done",
        args={"note": "   "},
        created="2026-10-17T12:00:01+00:00",
        action_id="a-blank",
    )
    blank = [row for row in queue.snapshot() if row.action_id == "a-blank"]
    assert blank[0].args == {}
    with pytest.raises(QueueError, match="1 to 500"):
        queue.enqueue(
            bot="primary",
            item="primary/sample-01",
            action="done",
            args={"note": "x" * 501},
            created="2026-10-17T12:00:02+00:00",
            action_id="a-long",
        )
    with pytest.raises(QueueError, match="1 to 500"):
        queue.enqueue(
            bot="primary",
            item="primary/sample-01",
            action="done",
            args={"note": "ok", "extra": 1},
            created="2026-10-17T12:00:03+00:00",
            action_id="a-extra",
        )
    with pytest.raises(QueueError, match="looks like a secret"):
        queue.enqueue(
            bot="primary",
            item="primary/sample-01",
            action="done",
            args={"note": "ghp_abcdefghijklmnopqrstuvwxyz"},
            created="2026-10-17T12:00:04+00:00",
            action_id="a-secret-note",
        )


def test_corrupt_action_file_is_left_in_place(tmp_path):
    directory = tmp_path / "queue"
    directory.mkdir()
    bad = directory / "a-bad.json"
    bad.write_text("{", encoding="utf-8")
    queue = ActionQueue(directory)
    assert queue.errors
    assert queue.next_batch(NOW + timedelta(seconds=30)) is None
    assert bad.read_text(encoding="utf-8") == "{"

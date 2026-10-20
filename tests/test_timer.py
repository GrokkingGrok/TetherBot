# SPDX-License-Identifier: GPL-2.0-or-later
"""The stopwatch is the file. Elapsed time is wall-clock math, never a tick."""

import json
import stat
import time
from io import StringIO
from pathlib import Path

import pytest

from tests.helpers import make_item
from tetherbot.daemon import BridgeDaemon
from tetherbot.timer import LIMIT_S, ClockSample, TimerError, TimerStore, elapsed_seconds


class Clock:
    def __init__(self) -> None:
        self.wall = 1_700_000_000.0
        self.boottime = 10_000.0
        self.boot_id = "boot-a"

    def __call__(self) -> ClockSample:
        return ClockSample(self.wall, self.boottime, self.boot_id)

    def advance(self, seconds: float, *, boot: float | None = None) -> None:
        self.wall += seconds
        self.boottime += seconds if boot is None else boot


def _store(tmp_path: Path, clock: Clock | None = None) -> tuple[TimerStore, Clock]:
    used = clock or Clock()
    return TimerStore(tmp_path, used), used


def test_running_and_paused_elapsed_across_segments(tmp_path: Path):
    store, clock = _store(tmp_path)
    store.start("", "Timer")
    clock.advance(10)
    assert elapsed_seconds(store.active(), clock.wall) == pytest.approx(10)
    store.pause()
    clock.advance(50)
    assert store.view()["elapsed_s"] == pytest.approx(10)
    store.resume()
    clock.advance(5)
    assert store.view()["elapsed_s"] == pytest.approx(15)
    store.pause()
    clock.advance(1)
    store.resume()
    clock.advance(2.5)
    assert store.view()["elapsed_s"] == pytest.approx(17.5)


def test_a_failed_write_leaves_the_previous_timer(tmp_path: Path, monkeypatch):
    store, clock = _store(tmp_path)
    store.start("primary/one", "Draft Q4 grant budget")
    clock.advance(4)
    before = json.loads((tmp_path / "timer.json").read_text(encoding="utf-8"))

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tetherbot.timer.write_private_json", _boom)
    with pytest.raises(TimerError) as caught:
        store.pause()
    assert caught.value.code == "failed"
    assert store.active()["state"] == "running"
    assert json.loads((tmp_path / "timer.json").read_text(encoding="utf-8")) == before
    assert "Could not save the timer" in str(caught.value)


def test_startup_running_paused_stopping_missing_and_corrupt(tmp_path: Path):
    clock = Clock()
    store, clock = _store(tmp_path, clock)
    assert store.view()["state"] == "idle"
    store.start("primary/q4-budget", "Draft Q4 grant budget")
    clock.advance(30)
    running = TimerStore(tmp_path, clock)
    assert running.view()["elapsed_s"] == pytest.approx(30)
    running.pause()
    paused = TimerStore(tmp_path, clock)
    clock.advance(100)
    assert paused.view()["state"] == "paused"
    assert paused.view()["elapsed_s"] == pytest.approx(30)

    path = tmp_path / "timer.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = "stopping"
    payload["accumulated_s"] = 30
    payload["item_key"] = "primary/q4-budget"
    path.write_text(json.dumps(payload), encoding="utf-8")
    again = TimerStore(tmp_path, clock)
    assert again.view()["state"] == "idle"
    assert again.totals()["primary/q4-budget"] == 30
    path.write_text(json.dumps(payload), encoding="utf-8")
    replay = TimerStore(tmp_path, clock)
    assert replay.totals()["primary/q4-budget"] == 30

    path.write_text("{", encoding="utf-8")
    broken = TimerStore(tmp_path, clock)
    first = broken.view()
    assert first["read_error"] == "The saved timer could not be read"
    assert broken.view()["state"] == "idle"
    assert "read_error" not in broken.view()
    assert list(tmp_path.glob("timer.json.bad-*"))
    assert not path.exists()


def test_stop_is_applied_once_and_undo_restores_it(tmp_path: Path):
    store, clock = _store(tmp_path)
    started = store.start("primary/q4-budget", "Draft Q4 grant budget")
    timer_id = started["timer_id"]
    clock.advance(10.9)
    store.pause()
    clock.advance(3)
    store.resume()
    clock.advance(4)
    result = store.stop()
    assert result["recorded_s"] == 14
    assert result["total_s"] == 14
    assert store.totals()["primary/q4-budget"] == 14
    clock.advance(2)
    assert store.undo_stop(timer_id) is True
    restored = store.view()
    assert restored["state"] == "running"
    assert restored["elapsed_s"] == pytest.approx(16.9)
    assert "primary/q4-budget" not in store.totals()
    store.stop()
    clock.advance(6)
    assert store.undo_stop(timer_id) is False


def test_standalone_stop_persists_until_assign_or_dismiss(tmp_path: Path):
    store, clock = _store(tmp_path)
    started = store.start("", "")
    clock.advance(8)
    result = store.stop()
    assert result["item_key"] == ""
    assert result["recorded_s"] == 8
    assert store.totals() == {}
    assert (tmp_path / "timer.json").is_file()
    view = store.view()
    assert view["state"] == "stopped"
    assert view["undo"]["kind"] == "undo"
    clock.advance(2)
    assert store.undo_stop(started["timer_id"]) is True
    restored = store.view()
    assert restored["state"] == "running"
    assert restored["elapsed_s"] == pytest.approx(10)
    store.stop()
    clock.advance(6)
    assert store.undo_stop(started["timer_id"]) is False
    kept = store.view()
    assert kept["state"] == "stopped"
    assert "undo" not in kept
    assert kept["elapsed_s"] == pytest.approx(10)
    reloaded = TimerStore(tmp_path, clock)
    assert reloaded.view()["state"] == "stopped"
    assert reloaded.assign(kept["timer_id"], "primary/one") is True
    assert reloaded.totals()["primary/one"] == 10
    assert reloaded.view()["state"] == "idle"
    assert not (tmp_path / "timer.json").exists()


def test_stopped_time_blocks_a_new_timer_until_dismissed(tmp_path: Path):
    store, clock = _store(tmp_path)
    store.start("", "")
    clock.advance(4)
    store.stop()
    with pytest.raises(TimerError) as exc:
        store.start("", "")
    assert exc.value.code == "busy"
    assert store.dismiss()["state"] == "idle"
    assert store.totals() == {}
    assert store.start("", "")["state"] == "running"


def test_edit_start_rejects_the_future_and_the_24_hour_limit(tmp_path: Path):
    store, clock = _store(tmp_path)
    store.start("", "Timer")
    clock.advance(60)
    moved = store.adjust_start(-300)
    assert moved["elapsed_s"] == pytest.approx(360)
    assert moved["state"] == "running"
    with pytest.raises(TimerError) as future:
        store.set_start(int(clock.wall) + 30)
    assert future.value.code == "invalid"
    assert "future" in str(future.value)
    with pytest.raises(TimerError) as limit:
        store.adjust_start(-LIMIT_S)
    assert "24 hour" in str(limit.value)
    store.pause()
    clock.advance(50)
    paused = store.adjust_start(-60)
    assert paused["state"] == "paused"
    assert paused["elapsed_s"] == pytest.approx(420)


def test_a_running_timer_can_be_attached_once(tmp_path: Path):
    store, clock = _store(tmp_path)
    store.start("", "")
    clock.advance(5)
    attached = store.attach("primary/one", "Pack the bag")
    assert attached["item_key"] == "primary/one"
    assert attached["state"] == "running"
    assert attached["elapsed_s"] == pytest.approx(5)
    with pytest.raises(TimerError) as exc:
        store.attach("primary/two", "Other")
    assert exc.value.code == "busy"


def test_clock_warnings_keep_set_and_discard(tmp_path: Path):
    store, clock = _store(tmp_path)
    store.start("primary/one", "Email venue about deposit")
    clock.advance(-30, boot=-30)
    assert store.poll() is True
    assert store.view()["warning"] == "clock_backward"
    kept = store.resolve("keep", 0)
    assert kept["warning"] is None
    assert kept["elapsed_s"] == pytest.approx(0)
    assert kept["state"] == "running"

    clock.advance(50, boot=50)
    store.pause()
    store.resume()
    clock.advance(400, boot=10)
    assert store.poll() is True
    assert store.view()["warning"] == "clock_jump"
    store.resolve("set", 90 * 60)
    set_view = store.view()
    assert set_view["warning"] is None
    assert set_view["elapsed_s"] == pytest.approx(90 * 60)

    clock.boot_id = "boot-b"
    clock.advance(10_000, boot=5)
    assert store.poll() is False

    clock.boot_id = "boot-a"
    fresh, clock = _store(tmp_path / "over", Clock())
    fresh.start("", "")
    clock.advance(LIMIT_S + 5)
    assert fresh.poll() is True
    assert fresh.view()["warning"] == "over_limit"
    fresh.resolve("keep", 0)
    assert fresh.view()["warning"] is None
    assert fresh.active()["limit_s"] == LIMIT_S * 2
    timer_id = fresh.view()["timer_id"]
    discarded = fresh.resolve("discard", 0)
    assert discarded["state"] == "idle"
    assert discarded["undo"]["kind"] == "undo"
    assert fresh.totals() == {}
    assert fresh.undo_stop(timer_id) is True
    assert fresh.view()["state"] == "running"


def test_timer_file_is_private(tmp_path: Path):
    store, _clock = _store(tmp_path)
    store.start("", "")
    mode = (tmp_path / "timer.json").stat().st_mode
    assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR


def test_api_start_stop_done_and_tracked_time(tmp_path: Path):
    daemon = BridgeDaemon(
        config_path=tmp_path / "config.toml",
        state_dir=tmp_path / "state",
        log_stream=StringIO(),
    )
    daemon.start()
    api = daemon.api
    assert api is not None
    assert daemon.store is not None
    daemon.store.replace_origin(
        "feed",
        [
            make_item(
                id="q4-budget",
                kind="todo",
                title="Draft Q4 grant budget",
                actions=["done"],
            )
        ],
        now=daemon.now(),
    )
    with pytest.raises(Exception) as missing:
        api.call("StartTimer", ("primary/missing",))
    assert "NotFound" in missing.value.error_name
    started = json.loads(api.call("StartTimer", ("primary/q4-budget",))[0])
    assert started["state"] == "running"
    assert started["item_title"] == "Draft Q4 grant budget"
    with pytest.raises(Exception) as busy:
        api.call("StartTimer", ("",))
    assert "TimerBusy" in busy.value.error_name
    api.call("PauseTimer", ())
    api.call("ResumeTimer", ())
    clock = Clock()
    clock.wall = time.time() + 9
    daemon.timer._clock = clock
    api.call("PerformAction", ("primary/q4-budget", "done", "{}"))
    idle = json.loads(api.call("GetTimer", ())[0])
    assert idle["state"] == "idle"
    assert idle["undo"]["recorded_s"] >= 8
    assert daemon.timer.totals()["primary/q4-budget"] == idle["undo"]["recorded_s"]
    assert api.call("UndoStopTimer", (idle["undo"]["timer_id"],)) == (True,)
    assert "primary/q4-budget" not in daemon.timer.totals()
    api.call("StopTimer", ())
    daemon.timer._clock = clock
    started_free = json.loads(api.call("StartTimer", ("",))[0])
    assert started_free["item_key"] == ""
    clock.wall += 30
    edited = json.loads(api.call("AdjustTimerStart", (-300,))[0])
    assert edited["elapsed_s"] >= 300
    attached = json.loads(api.call("AssignTimer", ("primary/q4-budget",))[0])
    assert attached["item_key"] == "primary/q4-budget"
    api.call("StopTimer", ())
    stopped = json.loads(api.call("GetTimer", ())[0])
    assert stopped["state"] == "idle"
    api.call("StartTimer", ("",))
    clock.wall += 4
    api.call("StopTimer", ())
    held = json.loads(api.call("GetTimer", ())[0])
    assert held["state"] == "stopped"
    clock.wall += 30
    still = json.loads(api.call("GetTimer", ())[0])
    assert still["state"] == "stopped"
    assert "undo" not in still
    dismissed = json.loads(api.call("DismissTimer", ())[0])
    assert dismissed["state"] == "idle"
    with pytest.raises(Exception) as future:
        api.call("StartTimer", ("",))
        api.call("SetTimerStart", (int(clock.wall) + 60,))
    assert "InvalidArgs" in future.value.error_name


def test_ctl_timer_status(tmp_path: Path):
    from tests.test_ctl import _context
    from tetherbot.ctl import main

    def call(method, _signature, _args):
        assert method == "GetTimer"
        return '{"state": "idle"}'

    context = _context(tmp_path, call_method=call)
    assert main(["timer", "status"], context) == 0
    assert "idle" in context.stdout.getvalue()

# SPDX-License-Identifier: GPL-2.0-or-later
"""One crash-proof stopwatch.

The file is the state. Elapsed time is wall-clock math over closed
segments plus the open one. Nothing here ticks, and nothing is written
to the feed. A method returns only after the new file is fsynced.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tetherbot import SCHEMA_VERSION
from tetherbot.files import ensure_private_dir, write_private_json

_LOG = logging.getLogger("tetherbot")
LIMIT_S = 24 * 60 * 60
MAX_TRACKED_S = 1000 * 24 * 3600
JUMP_S = 120.0
UNDO_S = 5.0
APPLIED_KEEP = 50
_RECORD_KINDS = frozenset({"session", "adjustment"})
_STATES = frozenset({"running", "paused", "stopping", "stopped"})
_WARNINGS = frozenset({"clock_backward", "clock_jump", "over_limit"})


class TimerError(Exception):
    """A timer change was refused. ``code`` is a short stable token."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ClockSample:
    """One reading of the wall clock, boot time, and boot id."""

    wall: float
    boottime: float
    boot_id: str


Clock = Callable[[], ClockSample]


def system_clock() -> ClockSample:
    """Read the real clocks. ``CLOCK_BOOTTIME`` counts through suspend."""

    boot_id = ""
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = ""
    flag = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)
    return ClockSample(wall=time.time(), boottime=time.clock_gettime(flag), boot_id=boot_id)


class TimerStore:
    """``timer.json`` and ``item-time.json`` under the bridge state directory."""

    def __init__(self, directory: Path, clock: Clock | None = None) -> None:
        self.directory = directory
        self.path = directory / "timer.json"
        self.times_path = directory / "item-time.json"
        self._clock = clock or system_clock
        self._timer: dict[str, Any] | None = None
        self._times = _empty_times()
        self._undo: dict[str, Any] | None = None
        self._read_error: str | None = None
        self.load()

    def load(self) -> None:
        """Read both files. A half-finished stop is applied. A bad file is renamed."""

        self._times = self._read_times()
        self._timer = None
        self._undo = None
        if not self.path.exists():
            return
        payload = self._read_timer_file()
        if payload is None:
            return
        state = payload.get("state")
        if state == "stopping":
            self._finish_stopping(payload)
            return
        self._timer = payload
        self._maybe_warn()

    def active(self) -> dict[str, Any] | None:
        """The running or paused timer, or None."""

        if self._timer is None or self._timer.get("state") not in {"running", "paused"}:
            return None
        return self._timer

    def holding(self) -> dict[str, Any] | None:
        """A timer that still occupies the one slot, including a stopped one."""

        state = None if self._timer is None else self._timer.get("state")
        if state not in {"running", "paused", "stopped"}:
            return None
        return self._timer

    def totals(self) -> dict[str, int]:
        rows = self._times.get("items")
        if not isinstance(rows, dict):
            return {}
        found: dict[str, int] = {}
        for key, row in rows.items():
            if isinstance(key, str) and isinstance(row, dict):
                total = _whole(row.get("total_s"))
                if total > 0:
                    found[key] = total
        return found

    def view(self) -> dict[str, Any]:
        """What ``GetTimer`` returns. Idle is explicit."""

        self._expire_undo()
        sample = self._clock()
        if self._timer is None:
            payload: dict[str, Any] = {"schema": SCHEMA_VERSION, "state": "idle"}
            if self._read_error:
                payload["read_error"] = self._read_error
                self._read_error = None
            public = self._public_undo(sample.wall)
            if public is not None:
                payload["undo"] = public
            return payload
        elapsed = elapsed_seconds(self._timer, sample.wall)
        payload = dict(self._timer)
        payload["elapsed_s"] = elapsed
        payload["now"] = sample.wall
        if elapsed < 0 and not payload.get("warning"):
            payload["warning"] = "clock_backward"
        if payload.get("state") == "stopped":
            public = self._public_undo(sample.wall)
            if public is not None:
                payload["undo"] = public
        return payload

    def poll(self) -> bool:
        """Minute check while a timer is running. True when a warning was saved."""

        return self._maybe_warn()

    def start(self, item_key: str, item_title: str) -> dict[str, Any]:
        if self.holding() is not None:
            raise TimerError("busy", "a timer is already running")
        if not isinstance(item_key, str) or not isinstance(item_title, str):
            raise TimerError("invalid", "item_key is invalid")
        sample = self._clock()
        timer = {
            "schema": SCHEMA_VERSION,
            "timer_id": _new_id(sample.wall),
            "state": "running",
            "item_key": item_key,
            "item_title": item_title,
            "created_at": sample.wall,
            "running_since": sample.wall,
            "accumulated_s": 0.0,
            "segments": [],
            "boot_id": sample.boot_id,
            "boottime_at_transition": sample.boottime,
            "wall_at_transition": sample.wall,
            "warning": None,
            "limit_s": LIMIT_S,
            "rev": 0,
        }
        self._commit(timer)
        return self.view()

    def pause(self) -> dict[str, Any]:
        timer = self._require("running")
        sample = self._clock()
        closed = _close_segment(timer, sample.wall)
        closed["state"] = "paused"
        closed["running_since"] = None
        _stamp(closed, sample)
        self._commit(closed)
        return self.view()

    def resume(self) -> dict[str, Any]:
        timer = self._require("paused")
        sample = self._clock()
        resumed = dict(timer)
        resumed["segments"] = list(timer.get("segments") or [])
        resumed["state"] = "running"
        resumed["running_since"] = sample.wall
        _stamp(resumed, sample)
        self._commit(resumed)
        return self.view()

    def stop(self) -> dict[str, Any]:
        timer = self.active()
        if timer is None:
            raise TimerError("no_timer", "no timer")
        if timer.get("item_key"):
            return self._stop(timer, record=True)
        return self._stop_unassigned(timer)

    def adjust_start(self, delta_s: int) -> dict[str, Any]:
        """Move the start instant by ``delta_s`` seconds. Negative starts earlier."""

        if isinstance(delta_s, bool) or not isinstance(delta_s, int):
            raise TimerError("invalid", "delta is invalid")
        timer = self.active()
        if timer is None:
            raise TimerError("no_timer", "no timer")
        sample = self._clock()
        end = _session_end(timer, sample.wall)
        start = end - elapsed_seconds(timer, end)
        return self._retarget(timer, start + delta_s, end, sample)

    def set_start(self, started_at: int) -> dict[str, Any]:
        """Replace the session start with a wall-clock instant."""

        if isinstance(started_at, bool) or not isinstance(started_at, int):
            raise TimerError("invalid", "started_at is invalid")
        timer = self.active()
        if timer is None:
            raise TimerError("no_timer", "no timer")
        sample = self._clock()
        end = _session_end(timer, sample.wall)
        return self._retarget(timer, float(started_at), end, sample)

    def dismiss(self) -> dict[str, Any]:
        """Drop a stopped unassigned timer. Nothing is recorded."""

        timer = self._timer
        if timer is None or timer.get("state") != "stopped":
            raise TimerError("no_timer", "no timer")
        self._remove_timer_file()
        self._timer = None
        self._undo = None
        return self.view()

    def attach(self, item_key: str, item_title: str) -> dict[str, Any]:
        """Put the current timer on an open todo.

        A running or paused timer keeps counting on that todo. A stopped
        unassigned timer is recorded and cleared.
        """

        if not isinstance(item_key, str) or not item_key or not isinstance(item_title, str):
            raise TimerError("invalid", "item_key is invalid")
        timer = self._timer
        if timer is None:
            raise TimerError("no_timer", "no timer")
        if timer.get("state") == "stopped":
            if not self.assign(str(timer.get("timer_id") or ""), item_key):
                raise TimerError("no_timer", "no timer")
            return self.view()
        if timer.get("state") not in {"running", "paused"}:
            raise TimerError("no_timer", "no timer")
        if timer.get("item_key"):
            raise TimerError("busy", "timer is already on a todo")
        updated = dict(timer)
        updated["segments"] = [list(pair) for pair in timer.get("segments") or []]
        updated["item_key"] = item_key
        updated["item_title"] = item_title
        self._commit(updated)
        return self.view()

    def undo_stop(self, timer_id: str) -> bool:
        self._expire_undo()
        undo = self._undo
        if undo is None or undo.get("kind") != "undo" or undo.get("timer_id") != timer_id:
            return False
        if undo.get("applied"):
            self._subtract(str(undo["item_key"]), int(undo["recorded_s"]), str(undo["timer_id"]))
        self._commit(dict(undo["timer"]))
        self._undo = None
        return True

    def assign(self, timer_id: str, item_key: str) -> bool:
        """Record a stopped standalone timer onto an open todo."""

        if not isinstance(item_key, str) or not item_key:
            raise TimerError("invalid", "item_key is invalid")
        self._expire_undo()
        timer = self._timer
        if (
            timer is not None
            and timer.get("state") == "stopped"
            and timer.get("timer_id") == timer_id
        ):
            recorded = _whole(timer.get("accumulated_s"))
            when = self._clock().wall
            self._apply(timer_id, item_key, recorded, when)
            self._remove_timer_file()
            self._timer = None
            self._undo = None
            return True
        undo = self._undo
        sample = self._clock()
        if undo is None or undo.get("kind") != "assign" or undo.get("timer_id") != timer_id:
            return False
        self._apply(timer_id, item_key, int(undo["recorded_s"]), sample.wall)
        self._undo = None
        return True

    def item_time(self, item_key: str) -> dict[str, Any]:
        """Saved records for one todo. The total is the sum of those records."""

        if not isinstance(item_key, str) or not item_key:
            raise TimerError("invalid", "item_key is invalid")
        row = self._row(item_key)
        records = [] if row is None else _public_records(row.get("records"))
        total = 0 if row is None else _whole(row.get("total_s"))
        return {
            "schema": SCHEMA_VERSION,
            "item_key": item_key,
            "total_s": total,
            "records": records,
        }

    def set_total(self, item_key: str, total_s: int) -> dict[str, Any]:
        """Store a direct total edit as an adjustment so the records still sum to it."""

        if not isinstance(item_key, str) or not item_key:
            raise TimerError("invalid", "item_key is invalid")
        if isinstance(total_s, bool) or not isinstance(total_s, int):
            raise TimerError("invalid", "total is invalid")
        if total_s < 0 or total_s > MAX_TRACKED_S:
            raise TimerError("invalid", "total is invalid")
        book = self._times
        items = book.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            book["items"] = items
        row = items.get(item_key)
        if not isinstance(row, dict):
            row = _empty_row()
            items[item_key] = row
        records = _record_list(row)
        delta = int(total_s) - _record_total(records)
        if delta == 0:
            return self.item_time(item_key)
        sample = self._clock()
        records.append(
            {
                "id": _new_id(sample.wall),
                "seconds": delta,
                "at": sample.wall,
                "kind": "adjustment",
            }
        )
        row["records"] = records
        _retotal(row)
        book["schema"] = SCHEMA_VERSION
        self._write_times(book)
        self._times = book
        return self.item_time(item_key)

    def delete_record(self, item_key: str, record_id: str) -> dict[str, Any]:
        """Remove one record and set the total to the sum of what remains."""

        if not isinstance(item_key, str) or not item_key:
            raise TimerError("invalid", "item_key is invalid")
        if not isinstance(record_id, str) or not record_id:
            raise TimerError("invalid", "record is invalid")
        book = self._times
        row = self._row(item_key)
        if row is None:
            raise TimerError("not_found", "time record not found")
        records = _record_list(row)
        kept = [record for record in records if record.get("id") != record_id]
        if len(kept) == len(records):
            raise TimerError("not_found", "time record not found")
        row["records"] = kept
        _retotal(row)
        book["schema"] = SCHEMA_VERSION
        self._write_times(book)
        self._times = book
        return self.item_time(item_key)

    def resolve(self, choice: str, seconds: int) -> dict[str, Any]:
        if choice not in {"keep", "set", "discard"}:
            raise TimerError("invalid", "choice is invalid")
        timer = self.active()
        if timer is None:
            raise TimerError("no_timer", "no timer")
        if choice == "discard":
            self._stop(timer, record=False, kind="undo")
            return self.view()
        sample = self._clock()
        updated = dict(timer)
        updated["segments"] = [list(pair) for pair in timer.get("segments") or []]
        if choice == "set":
            if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
                raise TimerError("invalid", "seconds is invalid")
            if seconds > 999 * 3600:
                raise TimerError("invalid", "seconds is invalid")
            updated["accumulated_s"] = float(seconds)
            updated["segments"] = []
            updated["state"] = "running"
            updated["running_since"] = sample.wall
        elif timer.get("warning") == "over_limit":
            updated["limit_s"] = int(timer.get("limit_s") or LIMIT_S) * 2
        elif timer.get("warning") == "clock_backward":
            updated["running_since"] = sample.wall
            updated["state"] = "running"
        updated["warning"] = None
        _stamp(updated, sample)
        self._commit(updated)
        return self.view()

    def _stop_unassigned(self, timer: dict[str, Any]) -> dict[str, Any]:
        """Leave a stopped timer on disk until it is assigned or dismissed."""

        sample = self._clock()
        closed = _close_segment(timer, sample.wall)
        recorded = _whole(closed["accumulated_s"])
        closed["accumulated_s"] = float(recorded)
        closed["state"] = "stopped"
        closed["running_since"] = None
        closed["item_key"] = ""
        closed["item_title"] = ""
        _stamp(closed, sample)
        self._commit(closed)
        self._undo = {
            "kind": "undo",
            "until": sample.wall + UNDO_S,
            "timer_id": closed["timer_id"],
            "item_key": "",
            "item_title": "",
            "recorded_s": recorded,
            "total_s": 0,
            "applied": False,
            "timer": timer,
        }
        return {
            "timer_id": closed["timer_id"],
            "item_key": "",
            "item_title": "",
            "recorded_s": recorded,
            "total_s": 0,
        }

    def _retarget(
        self,
        timer: dict[str, Any],
        new_start: float,
        end: float,
        sample: ClockSample,
    ) -> dict[str, Any]:
        if new_start > end:
            raise TimerError("invalid", "start is in the future")
        elapsed = end - new_start
        if elapsed < 0:
            raise TimerError("invalid", "start is in the future")
        limit = float(timer.get("limit_s") or LIMIT_S)
        if elapsed > limit:
            raise TimerError("invalid", "start is before the 24 hour limit")
        updated = dict(timer)
        if timer.get("state") == "running":
            updated["segments"] = []
            updated["accumulated_s"] = 0.0
            updated["running_since"] = new_start
        else:
            updated["segments"] = [[new_start, end]]
            updated["accumulated_s"] = float(elapsed)
            updated["running_since"] = None
        updated["warning"] = None
        _stamp(updated, sample)
        self._commit(updated)
        return self.view()

    def _stop(
        self,
        timer: dict[str, Any],
        *,
        record: bool,
        kind: str | None = None,
    ) -> dict[str, Any]:
        sample = self._clock()
        closed = _close_segment(timer, sample.wall)
        recorded = _whole(closed["accumulated_s"])
        closed["accumulated_s"] = float(recorded)
        closed["state"] = "stopping"
        closed["running_since"] = None
        closed["rev"] = int(timer.get("rev") or 0) + 1
        if not record:
            closed["item_key"] = ""
        _stamp(closed, sample)
        previous_times = json.loads(json.dumps(self._times))
        self._write_timer_file(closed)
        item_key = str(timer.get("item_key") or "")
        total = 0
        applied = False
        try:
            if record and item_key:
                total = self._apply(str(closed["timer_id"]), item_key, recorded, sample.wall)
                applied = True
            self._remove_timer_file()
        except Exception:
            self._times = previous_times
            try:
                self._write_times(previous_times)
                self._write_timer_file(timer)
            except TimerError:
                _LOG.info("could not save the timer")
            raise
        self._timer = None
        undo_kind = kind or ("undo" if item_key else "assign")
        self._undo = {
            "kind": undo_kind,
            "until": sample.wall + UNDO_S,
            "timer_id": closed["timer_id"],
            "item_key": item_key,
            "item_title": str(timer.get("item_title") or ""),
            "recorded_s": recorded,
            "total_s": total,
            "applied": applied,
            "timer": timer,
        }
        return {
            "timer_id": closed["timer_id"],
            "item_key": item_key,
            "item_title": str(timer.get("item_title") or ""),
            "recorded_s": recorded,
            "total_s": total,
        }

    def _require(self, state: str) -> dict[str, Any]:
        timer = self.active()
        if timer is None or timer.get("state") != state:
            raise TimerError("no_timer", "no timer")
        return timer

    def _commit(self, timer: dict[str, Any]) -> None:
        timer["rev"] = int(timer.get("rev") or 0) + 1
        self._write_timer_file(timer)
        self._timer = timer

    def _maybe_warn(self) -> bool:
        timer = self._timer
        if timer is None or timer.get("state") != "running" or timer.get("warning"):
            return False
        sample = self._clock()
        warning = _detect(timer, sample)
        if warning is None:
            return False
        updated = dict(timer)
        updated["segments"] = [list(pair) for pair in timer.get("segments") or []]
        updated["warning"] = warning
        self._commit(updated)
        return True

    def _finish_stopping(self, payload: dict[str, Any]) -> None:
        item_key = str(payload.get("item_key") or "")
        recorded = _whole(payload.get("accumulated_s"))
        timer_id = str(payload.get("timer_id") or "")
        when = float(payload.get("wall_at_transition") or 0)
        if item_key and timer_id:
            self._apply(timer_id, item_key, recorded, when)
        self._remove_timer_file()
        self._timer = None

    def _apply(self, timer_id: str, item_key: str, recorded_s: int, when: float) -> int:
        book = self._times
        applied = [row for row in book.get("applied") or [] if isinstance(row, str)]
        items = book.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            book["items"] = items
        row = items.get(item_key)
        if not isinstance(row, dict):
            row = _empty_row()
            items[item_key] = row
        if timer_id in applied:
            return _whole(row.get("total_s"))
        records = _record_list(row)
        records.append(
            {
                "id": timer_id,
                "seconds": int(recorded_s),
                "at": float(when),
                "kind": "session",
            }
        )
        row["records"] = records
        row["last_stopped_at"] = when
        _retotal(row)
        applied.append(timer_id)
        book["applied"] = applied[-APPLIED_KEEP:]
        book["schema"] = SCHEMA_VERSION
        self._write_times(book)
        self._times = book
        return _whole(row["total_s"])

    def _subtract(self, item_key: str, recorded_s: int, timer_id: str) -> None:
        book = self._times
        items = book.get("items")
        if isinstance(items, dict) and isinstance(items.get(item_key), dict):
            row = items[item_key]
            records = _record_list(row)
            kept = [record for record in records if record.get("id") != timer_id]
            if len(kept) == len(records):
                row["total_s"] = max(0, _whole(row.get("total_s")) - recorded_s)
                row["sessions"] = max(0, _whole(row.get("sessions")) - 1)
            else:
                row["records"] = kept
                _retotal(row)
        applied = [
            row
            for row in book.get("applied") or []
            if isinstance(row, str) and row != timer_id
        ]
        book["applied"] = applied
        self._write_times(book)

    def _row(self, item_key: str) -> dict[str, Any] | None:
        items = self._times.get("items")
        if not isinstance(items, dict):
            return None
        row = items.get(item_key)
        return row if isinstance(row, dict) else None

    def _expire_undo(self) -> None:
        undo = self._undo
        if undo is None:
            return
        if self._clock().wall > float(undo["until"]):
            self._undo = None

    def _public_undo(self, now: float) -> dict[str, Any] | None:
        undo = self._undo
        if undo is None or now > float(undo["until"]):
            return None
        return {
            "kind": undo["kind"],
            "until": undo["until"],
            "timer_id": undo["timer_id"],
            "item_key": undo["item_key"],
            "item_title": undo["item_title"],
            "recorded_s": undo["recorded_s"],
            "total_s": undo["total_s"],
        }

    def _read_timer_file(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._quarantine(self.path, "saved timer could not be read")
            return None
        if not isinstance(raw, dict) or not _schema_ok(raw) or raw.get("state") not in _STATES:
            self._quarantine(self.path, "saved timer could not be read")
            return None
        if not isinstance(raw.get("timer_id"), str):
            self._quarantine(self.path, "saved timer could not be read")
            return None
        return _normalized(raw)

    def _read_times(self) -> dict[str, Any]:
        if not self.times_path.exists():
            return _empty_times()
        try:
            raw = json.loads(self.times_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._quarantine(self.times_path, "saved item time could not be read")
            return _empty_times()
        if not isinstance(raw, dict) or not _schema_ok(raw):
            self._quarantine(self.times_path, "saved item time could not be read")
            return _empty_times()
        items = raw.get("items")
        applied = raw.get("applied")
        cleaned: dict[str, Any] = {}
        if isinstance(items, dict):
            for key, row in items.items():
                if isinstance(key, str) and isinstance(row, dict):
                    cleaned[key] = _normalize_item(row)
        return {
            "schema": SCHEMA_VERSION,
            "items": cleaned,
            "applied": (
                [row for row in applied if isinstance(row, str)]
                if isinstance(applied, list)
                else []
            ),
        }

    def _write_timer_file(self, timer: dict[str, Any]) -> None:
        try:
            write_private_json(self.path, timer)
        except OSError as exc:
            raise TimerError("failed", "Could not save the timer") from exc

    def _write_times(self, book: dict[str, Any]) -> None:
        try:
            write_private_json(self.times_path, book)
        except OSError as exc:
            raise TimerError("failed", "Could not save the timer") from exc

    def _remove_timer_file(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
            _fsync_dir(self.path.parent)
        except OSError as exc:
            raise TimerError("failed", "Could not save the timer") from exc

    def _quarantine(self, path: Path, message: str) -> None:
        stamp = int(time.time())
        target = path.with_name(f"{path.name}.bad-{stamp}")
        suffix = 1
        while target.exists():
            suffix += 1
            target = path.with_name(f"{path.name}.bad-{stamp}-{suffix}")
        try:
            path.replace(target)
            _fsync_dir(path.parent)
        except OSError:
            pass
        _LOG.info("%s", message)
        if path == self.path:
            self._read_error = "The saved timer could not be read"


def _session_end(timer: dict[str, Any], now: float) -> float:
    """The instant elapsed time stops growing. Paused time ends at the pause."""

    if timer.get("state") == "running":
        return now
    segments = timer.get("segments") or []
    if segments and isinstance(segments[-1], list) and len(segments[-1]) >= 2:
        return float(segments[-1][1])
    wall = timer.get("wall_at_transition")
    if isinstance(wall, (int, float)) and not isinstance(wall, bool):
        return float(wall)
    return now


def elapsed_seconds(timer: dict[str, Any], now: float) -> float:
    """``accumulated_s`` plus the open segment. Paused time does not grow."""

    accumulated = float(timer.get("accumulated_s") or 0)
    if timer.get("state") == "running" and timer.get("running_since") is not None:
        return accumulated + (now - float(timer["running_since"]))
    return accumulated


def _close_segment(timer: dict[str, Any], now: float) -> dict[str, Any]:
    closed = dict(timer)
    segments = [list(pair) for pair in timer.get("segments") or []]
    since = timer.get("running_since")
    accumulated = float(timer.get("accumulated_s") or 0)
    open_segment = (
        timer.get("state") == "running"
        and since is not None
        and timer.get("warning") != "clock_backward"
    )
    if open_segment:
        start = float(since)
        if now >= start:
            segments.append([start, now])
            accumulated += now - start
    closed["segments"] = segments
    closed["accumulated_s"] = accumulated
    return closed


def _detect(timer: dict[str, Any], sample: ClockSample) -> str | None:
    since = timer.get("running_since")
    if since is not None and sample.wall < float(since):
        return "clock_backward"
    if timer.get("boot_id") and timer.get("boot_id") == sample.boot_id:
        wall_delta = sample.wall - float(timer.get("wall_at_transition") or 0)
        boot_delta = sample.boottime - float(timer.get("boottime_at_transition") or 0)
        if abs(wall_delta - boot_delta) > JUMP_S:
            return "clock_jump"
    limit = float(timer.get("limit_s") or LIMIT_S)
    if elapsed_seconds(timer, sample.wall) > limit:
        return "over_limit"
    return None


def _stamp(timer: dict[str, Any], sample: ClockSample) -> None:
    timer["boot_id"] = sample.boot_id
    timer["boottime_at_transition"] = sample.boottime
    timer["wall_at_transition"] = sample.wall


def _normalized(raw: dict[str, Any]) -> dict[str, Any]:
    timer = dict(raw)
    timer["segments"] = [list(pair) for pair in raw.get("segments") or [] if isinstance(pair, list)]
    timer["accumulated_s"] = float(timer.get("accumulated_s") or 0)
    timer["limit_s"] = int(timer.get("limit_s") or LIMIT_S)
    timer["item_key"] = str(timer.get("item_key") or "")
    timer["item_title"] = str(timer.get("item_title") or "")
    warning = timer.get("warning")
    timer["warning"] = warning if warning in _WARNINGS else None
    return timer


def _schema_ok(payload: dict[str, Any]) -> bool:
    schema = payload.get("schema")
    if not isinstance(schema, str) or "/" not in schema:
        return False
    major = schema.split("/", 1)[1].split(".", 1)[0]
    return major == "1"


def _empty_times() -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "items": {}, "applied": []}


def _empty_row() -> dict[str, Any]:
    return {"total_s": 0, "sessions": 0, "last_stopped_at": 0.0, "records": []}


def _normalize_item(row: dict[str, Any]) -> dict[str, Any]:
    """One item row. A file from before records existed becomes one legacy record."""

    last = _stamp_time(row.get("last_stopped_at"))
    if "records" in row:
        records = _clean_records(row.get("records"))
        normalized = {
            "total_s": _record_total(records),
            "sessions": _session_count(records),
            "last_stopped_at": last,
            "records": records,
        }
        return normalized
    total = _whole(row.get("total_s"))
    records = []
    if total != 0:
        records.append(
            {
                "id": "legacy",
                "seconds": total,
                "at": last,
                "kind": "session",
            }
        )
    sessions = _whole(row.get("sessions"))
    if records and sessions <= 0:
        sessions = 1
    return {
        "total_s": total,
        "sessions": sessions,
        "last_stopped_at": last,
        "records": records,
    }


def _clean_records(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    found: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ident = item.get("id")
        kind = item.get("kind")
        seconds = item.get("seconds")
        if not isinstance(ident, str) or not ident or kind not in _RECORD_KINDS:
            continue
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            continue
        found.append(
            {
                "id": ident,
                "seconds": int(seconds),
                "at": _stamp_time(item.get("at")),
                "kind": kind,
            }
        )
    return found


def _record_list(row: dict[str, Any]) -> list[dict[str, Any]]:
    records = row.get("records")
    if not isinstance(records, list):
        records = []
        row["records"] = records
    return records


def _record_total(records: list[dict[str, Any]]) -> int:
    return sum(int(record["seconds"]) for record in records)


def _session_count(records: list[dict[str, Any]]) -> int:
    return sum(1 for record in records if record.get("kind") == "session")


def _retotal(row: dict[str, Any]) -> int:
    records = _clean_records(row.get("records"))
    row["records"] = records
    total = _record_total(records)
    row["total_s"] = total
    row["sessions"] = _session_count(records)
    return total


def _public_records(raw: object) -> list[dict[str, Any]]:
    return [
        {
            "id": record["id"],
            "seconds": int(record["seconds"]),
            "at": float(record["at"]),
            "kind": record["kind"],
        }
        for record in _clean_records(raw)
    ]


def _stamp_time(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _new_id(wall: float) -> str:
    day = datetime.fromtimestamp(wall, UTC).strftime("%Y%m%d")
    return f"tm-{day}-{secrets.token_hex(3)}"


def _whole(value: object) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _fsync_dir(path: Path) -> None:
    ensure_private_dir(path)
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)

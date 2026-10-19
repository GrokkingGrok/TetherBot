# TetherBot stopwatch and toolbar indicator

Status: approved. The Decisions section at the end is binding.

The top-bar icon is the robot glyph from the design mockups, shipped as symbolic SVGs (base, dot, ring, slash, and triangle). Mock todo titles in this file are generic examples.

Goal: track time on one task at a time from the top bar, and make the top-bar button say one thing at a glance. Losing tracked time is the worst failure, so recovery comes first.

## 1. Goals

- G1. One stopwatch at a time. Start it on its own, or tied to a todo.
- G2. Start from a todo row in the popup or the window. Pause, Resume, and Stop sit at the top of the popup.
- G3. Time from a todo-tied timer is recorded on that todo when it stops.
- G4. The timer survives an extension restart, a shell or bridge crash, logout, and reboot, with no lost time.
- G5. The top-bar button shows one thing at a time: the icon, or the icon plus elapsed time, with at most one small badge.
- G6. Color is never the only signal. Each state also has its own shape and its own screen-reader text.

## 2. Non-goals

- History, reports, charts, or exports. Later.
- More than one timer, or timers on asks, bills, or watch items.
- Sending time to the bot or writing it to the feed. Timer state stays on this machine for now (section 9).
- Counting ticks. Elapsed time is always computed from stored timestamps.

## 3. Top-bar states

The button has two slots. The **text slot** shows the timer. The **badge slot** shows the one most urgent attention state. Counts and detail live in the popup.

| State | Shape | Color | Priority | Text slot |
|---|---|---|---|---|
| Broken: bridge not running, `unconfigured`, `failed_closed`, or an auth reason (keyring locked, rejected key, routine not found) | Dimmed icon with a slash across it | red | 1 (highest) | none |
| Approval waiting: an open ask with `approve` in its actions | Filled dot | accent | 2 | time, if a timer exists |
| Overdue todo: an open, unsnoozed user todo past due | Hollow ring | red | 3 | time, if a timer exists |
| Clock warning (section 6.5) | Triangle with `!` | amber | 4 | `--:--` |
| Timer running | no badge | none | 5 | `1:42:10` |
| Timer paused | two pause bars before the time | text at 60% opacity | 5 | `0:25:03` |
| All clear | icon only | none | 6 | none |

Rules:

- Only the top priority badge shows. A timer and a badge show together, for example `1:42:10` with the accent dot.
- Broken hides the time. The bridge owns the timer, so the extension does not show a number it cannot confirm. The popup says the saved time is safe.
- Time format: `M:SS` under an hour, `H:MM:SS` from one hour. Use tabular figures so the button does not jitter (St support for `font-feature-settings: "tnum"` is **TBD, verify**).
- The badge has a cutout ring in the bar color so it reads against the icon at 16 px.
- The old count badge and the amber attention color on the icon go away. Amber stays for the bot row dot in the popup and for the clock warning.
- No blinking, pulsing, or animation in any state.

## 4. Popup

The stopwatch block is the first section of the popup, above the bot rows. See the mockup.

- **Running:** a "Timer running" label with a solid dot, the elapsed time in large text, the todo title and bot id (or "Timer" when standalone), then Pause and Stop.
- **Paused:** "Paused" with the pause glyph, the frozen time dimmed, then Resume and Stop.
- **Idle:** "No timer running" and a Start timer button for a standalone timer.
- **Clock warning:** the saved time, one sentence on why, and Keep, Set time..., and Discard (section 6.5).
- **Bridge down:** "Timer unavailable: bridge not running. Saved time is safe on disk and keeps counting."
- **After Stop:** "Recorded 1:42:10 on <title>" with a 5-second Undo, the same pattern as Done.

Todo rows (popup and window):

- An idle row has an icon-only play button next to Done. On hover or focus it can widen to "Start timer".
- The row that owns the timer shows a "Timing" label instead of the play button.
- A todo with recorded time shows a neutral chip, for example `1:42 tracked`.
- Starting a timer while another one exists asks one question in place: "Stop <title> and start this one?" with Switch and Cancel.
- The window detail pane gets the same Start timer button next to Done.

## 5. Timer data model

The bridge owns all timer state. The extension and the window only render it.

File: `$XDG_STATE_HOME/tetherbot/timer.json` (default `~/.local/state/tetherbot/timer.json`). Mode 0600. Written with `files.write_private_json`: write a temp file, fsync it, rename over the old file, fsync the directory. Written on every start, pause, resume, stop, and warning choice, and at no other time.

```json
{
  "schema": "tetherbot/1",
  "timer_id": "tm-20261019-8f3a2c",
  "state": "running",
  "item_key": "primary/q4-budget",
  "item_title": "Draft Q4 grant budget",
  "created_at": 1792419600.0,
  "running_since": 1792424135.2,
  "accumulated_s": 1830.0,
  "segments": [[1792419600.0, 1792421430.0]],
  "boot_id": "6c1f...",
  "boottime_at_transition": 88231.4,
  "wall_at_transition": 1792424135.2,
  "warning": null,
  "rev": 4
}
```

- `state` is `running`, `paused`, or `stopping`. No file means no timer.
- `item_key` is the global key `<bot>/<id>`, or `""` for a standalone timer. `item_title` is a snapshot, so the timer still has a name if the item leaves the feed.
- `running_since` is wall-clock Unix seconds, or `null` while paused.
- `accumulated_s` is the sum of closed `segments`. Each segment is `[start, end]` in wall-clock seconds.
- **elapsed = accumulated_s + (now - running_since)** while running, and `accumulated_s` while paused.
- `boot_id` comes from `/proc/sys/kernel/random/boot_id`. `boottime_at_transition` is `CLOCK_BOOTTIME`, which keeps counting through suspend. Both are only used to spot clock jumps (section 6.5).
- `rev` goes up by one on every write.

Recorded time per todo lives in `$XDG_STATE_HOME/tetherbot/item-time.json`, same write rules:

```json
{
  "schema": "tetherbot/1",
  "items": {
    "primary/q4-budget": {"total_s": 6130, "sessions": 3, "last_stopped_at": 1792430265.0}
  },
  "applied": ["tm-20261019-8f3a2c"]
}
```

`applied` keeps the last 50 timer ids, so applying a stop twice is a no-op.

## 6. Recovery

The rule: a transition is real only once it is on disk. A D-Bus method returns after the fsync. If the write fails, the method returns an error, memory is unchanged, and the popup says "Could not save the timer".

### 6.1 Extension restart, disable and enable, shell crash

The extension holds no timer state. On `enable()` it calls `GetTimer` and connects `TimerChanged`. While a timer runs and the button is visible, a 1-second GLib timeout redraws the text from `accumulated_s` and `running_since`. The timeout only redraws. It never adds to anything. It is removed in `disable()` and when the timer pauses or stops. Result: the same number as before the restart.

### 6.2 Bridge crash or kill

`Restart=on-failure` brings the bridge back, and D-Bus activation also starts it. At startup the bridge reads `timer.json`. A running timer kept counting the whole time because elapsed is wall-clock math. A `stopping` file means a stop was cut short: apply it to `item-time.json` (skipped if its id is in `applied`), then delete `timer.json`. An unreadable file is renamed to `timer.json.bad-<unix>`, the bridge logs one line, and the popup shows "The saved timer could not be read" once. The bridge never guesses a value.

### 6.3 Logout

The bridge stops with `graphical-session.target`. Nothing needs saving, because the last transition is already on disk. A running timer counts the time away. On the next login the bridge reads the file and the button shows the right time within the usual start-up delay (M25).

### 6.4 Reboot and power loss

Same as logout. Atomic rename means the file is either the old version or the new one, never half written. A new `boot_id` only means the jump check in 6.5 falls back to the plain checks.

### 6.5 Clock jumps

The bridge checks on start-up, on every `GetTimer`, and once a minute while a timer runs:

1. `now < running_since`: the clock went backward. Warning `clock_backward`.
2. Same `boot_id`, and wall time since the last transition differs from `CLOCK_BOOTTIME` since the last transition by more than 120 s: the clock was changed. Warning `clock_jump`.
3. Elapsed is over the sanity bound (default 24 h): warning `over_limit`.

A warning is written to `timer.json`. The text slot shows `--:--` and the amber triangle, and the extension never shows a negative or bogus number. Its own render also falls back to `--:--` if the math goes negative before the bridge says so. The timer keeps running underneath. The popup offers:

- **Keep:** accept the computed time and clear the warning. For `over_limit` the next check is at twice the bound. For `clock_backward`, the time before the jump is kept and counting restarts from now.
- **Set time...:** enter `H:MM`. The bridge sets `accumulated_s` to that, `running_since` to now, and clears the warning.
- **Discard:** delete the timer and record nothing. It has the same 5-second Undo as Stop.

Normal NTP slews are small and stay under the 120 s threshold. Suspend is counted by `CLOCK_BOOTTIME`, so it does not look like a jump.

## 7. What Stop records

Stop writes `state: stopping` with the final segment closed (fsync), adds `accumulated_s` to that todo's `total_s` in `item-time.json`, increments `sessions`, sets `last_stopped_at`, adds the timer id to `applied` (fsync), then deletes `timer.json`. The recorded value is rounded down to whole seconds.

- A standalone timer records nothing. Stop shows the time with Undo and then it is gone.
- Undo within 5 seconds subtracts the amount, drops the id from `applied`, and restores the timer as it was. Time during the undo window counts, as if Stop never happened.
- Done on a todo that owns the timer stops the timer first, records the time, then sends Done.
- An item that leaves the feed while timed keeps running under `item_title`. Stop records under its key anyway.
- Nothing is written to the feed or `desktop/state.json`, and nothing is sent to the bot.

## 8. D-Bus additions

Additive within `io.github.grokkinggrok.TetherBot1`. Update `data/io.github.grokkinggrok.TetherBot1.xml` and the extension copy together. Timer payloads are JSON strings (`s`), like items.

| Signature | Behavior |
|---|---|
| `StartTimer(s item_key) -> s timer_json` | `""` starts a standalone timer. Otherwise the key must be an open todo, or `Error.NotFound`. If a timer exists, `Error.TimerBusy`, and the client calls `StopTimer` first to switch |
| `PauseTimer() -> s timer_json` | Closes the open segment. `Error.NoTimer` if nothing runs |
| `ResumeTimer() -> s timer_json` | Sets `running_since` to now. `Error.NoTimer` if nothing is paused |
| `StopTimer() -> s result_json` | `{timer_id, item_key, recorded_s, total_s}`. Works when running or paused |
| `UndoStopTimer(s timer_id) -> b` | Within 5 s of that stop or discard. False after that |
| `GetTimer() -> s timer_json` | `{state: "idle"}` when there is none. Otherwise the file fields plus `elapsed_s` and `now` from the bridge |
| `ResolveTimerWarning(s choice, x seconds) -> s timer_json` | `choice` is `keep`, `set`, or `discard`. `seconds` is used only for `set` |
| `AssignStoppedTimer(s timer_id, s item_key) -> b` | Within 5 s of stopping a standalone timer, record that time on an open todo. False after the window or when the id does not match |

| Signal | When |
|---|---|
| `TimerChanged(s timer_json)` | After every write to `timer.json` or `item-time.json`, and when a warning appears. Not every second |

`GetItems` items gain an optional `time_tracked_s`, filled from `item-time.json`. The extension computes the badge from the existing `Counts`, `State`, `StateReason`, and `GetItems` with `due:overdue`. A typed `Attention` property is a later option if that gets slow. `tetherbotctl timer` (status, start, pause, resume, stop) is a small add for scripts and manual checks.

## 9. Later: report time to the bot

Not now. One option: the Done action body carries `time_tracked_s` when the todo has recorded time. That adds no extra run, because it rides on a POST that already happens. A separate time action would spend a run each time, so it would have to be batched.

## 10. Accessibility

- Every state has a distinct shape: no badge, dot, ring, triangle, slash, pause bars, dashes. The states read in grayscale and with any accent color, including a red accent.
- No flashing or motion. The seconds text is the only thing that changes.
- The button's accessible name names the state in words, and is updated once a minute, not every second:
  - `TetherBot: all clear`
  - `TetherBot: timer running, 1 hour 42 minutes, Draft Q4 grant budget`
  - `TetherBot: timer paused at 25 minutes, Email venue about deposit`
  - `TetherBot: 1 approval waiting`
  - `TetherBot: timer running, 1 hour 42 minutes. 1 approval waiting`
  - `TetherBot: 2 overdue todos`
  - `TetherBot: timer needs a check`
  - `TetherBot: bridge not running`
- The tooltip uses the same text. `extension/view_checks.js` expects the old `2 asks, 3 todos` names, so those tests change.
- The row play button is icon-only, with the accessible name `Start timer: <title>`. Pause, Resume, Stop, Keep, Set time..., and Discard have text labels.
- Keyboard: the timer buttons come first in the popup's focus order. `Space` on a focused todo row could toggle its timer (**TBD, verify** that it does not clash with Done).
- High contrast theme: badges keep the bar-colored cutout so they stay visible.

## 11. Tests and manual checks

Unit tests, with an injected wall clock and boottime:

- Elapsed math while running and paused, across many segments.
- Each write happens before the method returns. A failed write leaves the state unchanged.
- Start-up with `running`, `paused`, `stopping`, a missing file, and a corrupt file.
- Stop is applied once even when replayed. Undo reverses it exactly.
- Clock backward, a jump in the same boot, a new boot, and over 24 h each give the right warning. Keep, set, and discard.
- Badge priority for every combination of the inputs in section 3, and the accessible names.

Manual checks, next free numbers in [MANUAL-CHECKS.md](MANUAL-CHECKS.md):

- M27. Start a timer from a todo row in the popup. The button shows the time. The row shows Timing. Pause, Resume, and Stop work. The todo shows `tracked` time, in the window too.
- M28. Disable and enable the extension, and restart a nested devkit shell, while a timer runs. The time matches a phone stopwatch within 2 s.
- M29. `systemctl --user kill -s KILL tetherbot` while running. After the restart the time is still right.
- M30. Log out for 5 minutes and log back in. The time includes the 5 minutes.
- M31. Reboot with a paused timer. It is still paused at the same value.
- M32. Kill the bridge in a loop while a script calls start, pause, and resume. `timer.json` always parses.
- M33. Turn off NTP and set the clock back 1 hour. The button shows `--:--` and the triangle. Keep, Set time..., and Discard each work. Turn NTP back on.
- M34. Stop, then Undo within 5 s. The recorded total goes back. Done on a timed todo records the time first.
- M35. Stop the bridge with an approval waiting and a timer running. The slash shows and the time hides. Start it again. The time and the dot come back.
- M36. With Orca, focus the button in each state and hear the names in section 10. Check the states in grayscale.

## 12. Open questions

1. Time away. Should a running timer keep counting through logout, suspend, and power-off (proposed: yes, it is a wall-clock stopwatch), or pause on logout or suspend?
2. Standalone timers. Stop records nothing, as proposed? Or offer "Add to a todo" on Stop?
3. Switching. Confirm in place before stopping one timer to start another (proposed), or switch without asking?
4. Done on a timed todo. Stop and record automatically (proposed)?
5. Broken plus timer. Hide the time (proposed), or show the last known time dimmed?
6. Broken scope. Which `degraded` reasons get the slash? Proposed: auth and keyring reasons only. A stale feed or a rejected push shows only in the popup.
7. Clock warning color. The decided colors are accent and red. Amber for the warning is proposed here. Its rank is between overdue and timer.
8. Sanity bound. 24 h fixed, or a setting?
9. Time format under an hour. `42:10` (proposed) or `0:42:10`?
10. Overdue scope. Only todos owned by the user (`owner: user`), and not snoozed ones (proposed)?
11. Later: report time to the bot inside the Done action (section 9)?

## Decisions (approved)

- Keep counting through logout, suspend, and power-off. Elapsed time is wall clock.
- Clock warning (clock moved backward, or more than 24 hours elapsed): amber triangle, `--:--`, and Keep, Set time..., or Discard. The 24-hour limit is fixed for now.
- Starting a timer while another is running asks for confirmation first.
- Done on a timed todo stops the timer and records the time on that todo.
- After Stop, a 5-second Undo, the same as Done.
- Stopping a standalone timer shows "Add to a todo" for 5 seconds, like Undo. If it isn't used, the prompt goes away on its own and the time is dropped. No tap is needed to dismiss it.
- Time format: `42:10` under an hour, `1:42:10` at an hour or more.
- Slash (broken) only for a bridge that is down or an auth or keyring error. Smaller problems, like a stale feed, show only in the popup.
- Paused: pause bars and dimmed time. Broken hides the time.
- The placeholder robot glyph in the mockups becomes the real TetherBot icon. Ship it as symbolic SVGs, one per badge state (base, dot, ring, slash, triangle), and replace the envelope icon.

# SPDX-License-Identifier: GPL-2.0-or-later
"""``tetherbotctl``: status, enable, secret set, and webhook test.

Secrets are read from the terminal with ``getpass`` and stored in the
secret service. They are not printed, logged, or sent over D-Bus. A webhook
test prints only the HTTP status code and does not follow redirects.
``repo setup`` is not implemented. Importing this module does not open a
socket or import PyGObject.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from tetherbot.adapters.webhook_sender import ping_body
from tetherbot.clipboard_policy import format_clipboard_debug
from tetherbot.config import ConfigError, action_slots, load_config, save_adapter_enabled
from tetherbot.daemon import default_config_path, default_state_dir
from tetherbot.dbus_service import BUS_NAME, INTERFACE, OBJECT_PATH
from tetherbot.secrets import SecretError, SecretStore, open_secret_store

_ADAPTERS = {
    "webhook": "webhook-sender",
    "repo": "github-poller",
    "official": "official",
}
_POST_TIMEOUT = 30


class CtlError(Exception):
    """A command failed. The message does not contain a secret or a URL."""


@dataclass
class CtlContext:
    config_path: Path
    stdout: TextIO
    stderr: TextIO
    prompt: Callable[[str], str]
    secrets: SecretStore
    properties: Callable[[], Mapping[str, object] | None]
    set_enabled: Callable[[str, bool], None] | None
    post: Callable[[str, str], int]
    resume: Callable[[str], None] | None = None
    queue: Callable[[], list[Mapping[str, object]] | None] | None = None
    call_method: Callable[[str, str, tuple[object, ...]], object] | None = None
    state_dir: Path | None = None


def main(argv: list[str] | None = None, context: CtlContext | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        parsed = _parser().parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)
    if context is None:
        context = default_context()
    try:
        return _dispatch(parsed, context)
    except (CtlError, ConfigError, SecretError) as exc:
        print(str(exc), file=context.stderr)
        return 1
    except KeyboardInterrupt:
        print("cancelled", file=context.stderr)
        return 1


def default_context() -> CtlContext:
    path = default_config_path()
    return CtlContext(
        config_path=path,
        stdout=sys.stdout,
        stderr=sys.stderr,
        prompt=getpass.getpass,
        secrets=open_secret_store(),
        properties=dbus_properties,
        set_enabled=_set_enabled_live(path),
        post=post_ping,
        resume=_resume_live(path),
        queue=_live_queue,
    )


def post_ping(url: str, key: str, *, opener: urllib.request.OpenerDirector | None = None) -> int:
    """POST a ping. Returns the status code and does not read the body aloud."""

    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        raise CtlError("webhook url must be https")
    request = urllib.request.Request(
        url,
        data=ping_body(),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    client = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with client.open(request, timeout=_POST_TIMEOUT) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        raise CtlError("webhook test failed") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow a redirect. That would send the bearer token again."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def dbus_properties() -> dict[str, object] | None:
    """Read status from the running bridge, or None when it is not on the bus."""

    bus = _session_bus()
    if bus is None or not _name_owned(bus):
        return None
    try:
        return {
            "state": str(_property(bus, "State")),
            "reason": str(_property(bus, "StateReason")),
            "mode": str(_property(bus, "Mode")),
            "queue": int(_property(bus, "QueueLength")),
        }
    except Exception:
        return None


def resume_parked_ids(
    slot: str,
    bots: Mapping[str, str],
    rows: list[Mapping[str, object]],
) -> list[str]:
    """Parked action ids whose bot uses ``slot``. The rows are not logged."""

    return [
        str(row["action_id"])
        for row in rows
        if row.get("state") == "parked" and bots.get(str(row.get("bot"))) == slot
    ]


def dbus_set_adapter(name: str, enabled: bool) -> None:
    bus = _session_bus()
    if bus is None:
        raise CtlError("cannot update the running bridge")
    try:
        glib, gio = _gio()
        bus.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            "SetAdapterEnabled",
            glib.Variant("(sb)", (name, enabled)),
            None,
            gio.DBusCallFlags.NONE,
            2000,
            None,
        )
    except Exception:
        raise CtlError("cannot update the running bridge") from None


def _live_queue() -> list[dict[str, object]] | None:
    if dbus_properties() is None:
        return None
    try:
        return dbus_get_queue()
    except CtlError:
        return None


def dbus_get_queue() -> list[dict[str, object]]:
    reply = _dbus_call("GetQueue", None, "(s)")
    if reply is None:
        raise CtlError("cannot update the running bridge")
    payload = reply.unpack()[0]
    rows = json.loads(str(payload))
    if not isinstance(rows, list):
        raise CtlError("cannot update the running bridge")
    return [row for row in rows if isinstance(row, dict)]


def dbus_retry_parked(action_id: str) -> None:
    glib = _gio()[0]
    _dbus_call("RetryParked", glib.Variant("(s)", (action_id,)), None)


def _resume_live(path: Path) -> Callable[[str], None]:
    def _resume(slot: str) -> None:
        if dbus_properties() is None or not path.is_file():
            return
        config = load_config(path)
        bots = {name: bot.webhook_slot for name, bot in config.bots.items()}
        if slot not in bots.values():
            return
        for action_id in resume_parked_ids(slot, bots, dbus_get_queue()):
            dbus_retry_parked(action_id)

    return _resume


def _dbus_call(method: str, args: object, reply: str | None) -> object:
    bus = _session_bus()
    if bus is None:
        raise CtlError("cannot update the running bridge")
    try:
        glib, gio = _gio()
        reply_type = None if reply is None else glib.VariantType(reply)
        return bus.call_sync(  # type: ignore[attr-defined]
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            method,
            args,
            reply_type,
            gio.DBusCallFlags.NONE,
            2000,
            None,
        )
    except CtlError:
        raise
    except Exception:
        raise CtlError("cannot update the running bridge") from None


def _dispatch(args: argparse.Namespace, context: CtlContext) -> int:
    if args.command == "status":
        return _status(context)
    if args.command == "enable":
        return _switch(args.name, True, context)
    if args.command == "disable":
        return _switch(args.name, False, context)
    if args.command == "secret":
        return _secret_set(args.slot, context)
    if args.command == "webhook":
        return _webhook_test(args.bot, context)
    if args.command == "timer":
        return _timer(args, context)
    if args.command == "clipboard-debug":
        return _clipboard_debug(context)
    if args.command == "window-faults":
        return _window_faults(context)
    raise CtlError("unknown command")


def _status(context: CtlContext) -> int:
    live = context.properties()
    if live is not None:
        _write_status(
            context.stdout,
            state=str(live["state"]),
            reason=str(live["reason"]),
            mode=str(live["mode"]) or None,
            queue=int(live["queue"]),
            parked=_parked_count(context),
            running=True,
        )
        return 0
    state, reason, mode = _local_status(context.config_path)
    _write_status(
        context.stdout,
        state=state,
        reason=reason,
        mode=mode,
        queue=None,
        parked=None,
        running=False,
    )
    return 0


def _switch(name: str, enabled: bool, context: CtlContext) -> int:
    adapter = _ADAPTERS[name]
    if context.set_enabled is not None:
        context.set_enabled(adapter, enabled)
    else:
        save_adapter_enabled(context.config_path, adapter, enabled)
    word = "enabled" if enabled else "disabled"
    print(f"{word} {name}", file=context.stdout)
    return 0


def _secret_set(slot: str, context: CtlContext) -> int:
    try:
        if slot == "github-token":
            token = context.prompt("GitHub token: ")
            context.secrets.put_github_token(slot, token)
        else:
            url = context.prompt("Webhook URL: ")
            key = context.prompt("Webhook key: ")
            context.secrets.put_webhook(slot, url, key)
    except EOFError as exc:
        raise CtlError("cancelled") from exc
    print(f"stored {slot}", file=context.stdout)
    if context.resume is not None:
        context.resume(slot)
    return 0


def _webhook_test(bot: str, context: CtlContext) -> int:
    if not context.config_path.is_file():
        raise CtlError("config.toml is missing")
    config = load_config(context.config_path)
    slots = action_slots(config, bot)
    if not slots:
        raise CtlError("bot has no webhook slot")
    secret = None
    for slot in slots:
        secret = context.secrets.get_webhook(slot)
        if secret is not None:
            break
    if secret is None:
        raise CtlError("webhook secret is not stored")
    code = context.post(secret.url, secret.key)
    print(code, file=context.stdout)
    return 0


def _local_status(path: Path) -> tuple[str, str, str | None]:
    if not path.is_file():
        return "unconfigured", "config.toml is missing", None
    try:
        config = load_config(path)
    except ConfigError as exc:
        return "failed_closed", str(exc), None
    enabled = sorted(
        name
        for table in (config.adapters, config.sinks)
        for name, row in table.items()
        if row.enabled
    )
    if not enabled:
        return "unconfigured", "no adapter is enabled", config.mode
    return "degraded", "not started: " + ", ".join(enabled), config.mode


def _parked_count(context: CtlContext) -> int | None:
    """Parked rows from GetQueue. Pending actions stay on the ``queue:`` line."""

    if context.queue is None:
        return None
    rows = context.queue()
    if rows is None:
        return None
    return sum(1 for row in rows if row.get("state") == "parked")


def _write_status(
    stdout: TextIO,
    *,
    state: str,
    reason: str,
    mode: str | None,
    queue: int | None,
    parked: int | None,
    running: bool,
) -> None:
    print(state, file=stdout)
    print(f"reason: {reason}", file=stdout)
    if mode:
        print(f"mode: {mode}", file=stdout)
    if queue is not None:
        print(f"queue: {queue}", file=stdout)
    if parked is not None:
        print(f"parked: {parked}", file=stdout)
    print("running: yes" if running else "running: no", file=stdout)


def _set_enabled_live(path: Path) -> Callable[[str, bool], None]:
    def _set(adapter: str, enabled: bool) -> None:
        if dbus_properties() is not None:
            dbus_set_adapter(adapter, enabled)
        else:
            save_adapter_enabled(path, adapter, enabled)

    return _set


def _timer(args: argparse.Namespace, context: CtlContext) -> int:
    action = args.timer_command
    if action == "status":
        payload = _timer_call(context, "GetTimer", "()", ())
    elif action == "start":
        payload = _timer_call(context, "StartTimer", "(s)", (args.item or "",))
    elif action == "pause":
        payload = _timer_call(context, "PauseTimer", "()", ())
    elif action == "resume":
        payload = _timer_call(context, "ResumeTimer", "()", ())
    elif action == "stop":
        payload = _timer_call(context, "StopTimer", "()", ())
    else:
        raise CtlError("unknown command")
    print(payload if isinstance(payload, str) else json.dumps(payload), file=context.stdout)
    return 0


def _timer_call(context: CtlContext, method: str, signature: str, args: tuple[object, ...]) -> str:
    if context.call_method is not None:
        result = context.call_method(method, signature, args)
        return result if isinstance(result, str) else json.dumps(result)
    return _dbus_timer(method, signature, args)


def _dbus_timer(method: str, signature: str, args: tuple[object, ...]) -> str:
    bus = _session_bus()
    if bus is None or not _name_owned(bus):
        raise CtlError("bridge is not running")
    glib, gio = _gio()
    out = "(s)"
    try:
        reply = bus.call_sync(  # type: ignore[attr-defined]
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE,
            method,
            glib.Variant(signature, args),
            glib.VariantType(out),
            gio.DBusCallFlags.NONE,
            8000,
            None,
        )
    except Exception as exc:
        raise CtlError("could not save the timer") from exc
    unpacked = reply.unpack()
    if isinstance(unpacked, tuple) and unpacked:
        return str(unpacked[0])
    return str(unpacked)


def window_faults_path(state_dir: Path | None = None) -> Path:
    """The window process appends fault traces here. The text is not a secret."""

    directory = state_dir if state_dir is not None else default_state_dir()
    return directory / "window-faults.log"


def _window_faults(context: CtlContext) -> int:
    """Print the window fault log. A missing file prints nothing."""

    path = window_faults_path(context.state_dir)
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CtlError("could not read window faults") from exc
    if text and not text.endswith("\n"):
        text = f"{text}\n"
    print(text, file=context.stdout, end="")
    return 0


def _clipboard_debug(context: CtlContext) -> int:
    """Print the last offer's types and decision. The text is not read aloud."""

    directory = context.state_dir if context.state_dir is not None else default_state_dir()
    path = directory / "clipboard.json"
    payload: object = None
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            payload = None
    print(format_clipboard_debug(payload), file=context.stdout, end="")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tetherbotctl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    enable = commands.add_parser("enable")
    enable.add_argument("name", choices=sorted(_ADAPTERS))
    disable = commands.add_parser("disable")
    disable.add_argument("name", choices=sorted(_ADAPTERS))
    secret = commands.add_parser("secret")
    secret_commands = secret.add_subparsers(dest="secret_command", required=True)
    set_secret = secret_commands.add_parser("set")
    set_secret.add_argument("slot")
    webhook = commands.add_parser("webhook")
    webhook_commands = webhook.add_subparsers(dest="webhook_command", required=True)
    test = webhook_commands.add_parser("test")
    test.add_argument("bot")
    timer = commands.add_parser("timer")
    timer_commands = timer.add_subparsers(dest="timer_command", required=True)
    timer_commands.add_parser("status")
    start = timer_commands.add_parser("start")
    start.add_argument("--item", default="")
    timer_commands.add_parser("pause")
    timer_commands.add_parser("resume")
    timer_commands.add_parser("stop")
    commands.add_parser("clipboard-debug")
    commands.add_parser("window-faults")
    return parser


def _gio() -> tuple[object, object]:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as exc:
        raise CtlError("session bus is not available") from exc
    return GLib, Gio


def _session_bus() -> object | None:
    try:
        _glib, gio = _gio()
    except CtlError:
        return None
    try:
        return gio.bus_get_sync(gio.BusType.SESSION, None)
    except Exception:
        return None


def _name_owned(bus: object) -> bool:
    try:
        glib, gio = _gio()
        reply = bus.call_sync(  # type: ignore[attr-defined]
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            glib.Variant("(s)", (BUS_NAME,)),
            glib.VariantType("(b)"),
            gio.DBusCallFlags.NONE,
            2000,
            None,
        )
    except Exception:
        return False
    return bool(reply.unpack()[0])


def _property(bus: object, name: str) -> object:
    glib, gio = _gio()
    reply = bus.call_sync(  # type: ignore[attr-defined]
        BUS_NAME,
        OBJECT_PATH,
        "org.freedesktop.DBus.Properties",
        "Get",
        glib.Variant("(ss)", (INTERFACE, name)),
        glib.VariantType("(v)"),
        gio.DBusCallFlags.NONE,
        2000,
        None,
    )
    return reply.unpack()[0]


if __name__ == "__main__":
    raise SystemExit(main())

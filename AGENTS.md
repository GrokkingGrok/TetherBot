# Working on TetherBot

Read [docs/SPEC.md](docs/SPEC.md) before changing behavior. It is the architecture source of truth. [docs/ROADMAP.md](docs/ROADMAP.md) is the milestone checklist. [docs/PROTOCOL.md](docs/PROTOCOL.md) is the wire contract.

## How to build

- Work one milestone at a time: v0.1, then v0.2, then v1.0. Leave later features as stubs.
- The tree is a scaffold. Add interfaces, tests, and TODOs before production behavior.
- The GNOME extension uses the session bus only. Do not import Soup, open sockets, spawn network processes, or call `fetch` from `extension/`.
- Secrets stay in the desktop secret service, inside the bridge process. Keep them out of the shell process, the prefs process, gsettings, config files, unit files, logs, the queue, D-Bus messages, environment variables, and git.
- Fail closed on an unknown protocol schema version. Keep the last good items, mark them stale, and report that TetherBot needs an update. Do not guess.
- Adapters stay off until the user enables them by name.
- Do not add runtime Python dependencies. PyGObject, libsecret, and git come from the OS. HTTP uses `urllib.request` on a worker thread, posted back to the GLib loop. Git uses the `git` CLI via `subprocess`.

## Checks

```bash
pytest
ruff check .
```

Anything marked **TBD, verify** in the spec is an open checkbox in the roadmap. Verify it before relying on it.

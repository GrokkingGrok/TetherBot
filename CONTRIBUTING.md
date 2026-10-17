# Contributing

TetherBot is pre-alpha. Read [docs/SPEC.md](docs/SPEC.md) first, then take the next unchecked item in [docs/ROADMAP.md](docs/ROADMAP.md). Build one milestone at a time.

## Ground rules

- The extension talks to the bridge over D-Bus only. No network calls and no secrets in the shell process.
- Secrets stay in the desktop secret service. Do not put them in config, gsettings, unit files, logs, the queue, D-Bus messages, environment variables, or git.
- An unknown protocol schema version fails closed. Do not invent a mapping.
- Do not add runtime pip dependencies. PyGObject is an operating-system package. Use `urllib.request` for HTTP and the `git` CLI for git.
- Keep adapters disabled until the user turns them on.

## Checks

```bash
python -m pip install pytest ruff
pytest
ruff check .
```

The package metadata targets Python 3.13. The scaffold tests use only the standard library.

## Changes

Prefer a small pull request that finishes one roadmap item and leaves the tests green. If something in the spec is marked **TBD, verify**, check it against the live system and record the result in the roadmap instead of guessing.

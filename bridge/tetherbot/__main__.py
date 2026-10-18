# SPDX-License-Identifier: GPL-2.0-or-later
"""Start the bridge process.

The process loads config and state, then blocks in a GLib main loop. It
does not export D-Bus and does not open a network connection.
"""

import sys

from tetherbot.daemon import BridgeDaemon


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("tetherbot: no arguments are accepted yet", file=sys.stderr)
        return 2
    try:
        return BridgeDaemon().run(install_signals=True)
    except ImportError:
        print(
            "tetherbot: PyGObject is required. Install the OS package python3-gobject.",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        detail = exc.strerror or exc.__class__.__name__
        print(f"tetherbot: cannot start ({detail})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

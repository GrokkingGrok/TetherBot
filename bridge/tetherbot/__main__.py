# SPDX-License-Identifier: GPL-2.0-or-later
"""Module entry point. The daemon is intentionally not started."""

import sys


def main() -> int:
    print(
        "tetherbot: the bridge daemon is not implemented yet (pre-alpha scaffold).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

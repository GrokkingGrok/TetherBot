#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""HTTPS server on 127.0.0.1 that answers every request with HTTP 400.

Manual check M6 points a webhook slot at the printed URL. The process
discards the body and never prints the Authorization header.

Python checks the server certificate. This script writes a one-day
certificate and a bundle that adds it to the system trust store. Use that
bundle only for this check:

    systemctl --user set-environment SSL_CERT_FILE=<bundle printed below>
    systemctl --user restart tetherbot

Clear it afterwards:

    systemctl --user unset-environment SSL_CERT_FILE
    systemctl --user restart tetherbot

The bundle includes the system certificate store, so other HTTPS calls keep
working while it is set. Paste the URL and a throwaway key into
``tetherbotctl secret set <slot>``. Do not put them in config.toml.
"""

from __future__ import annotations

import argparse
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    """Answer 400 and do not log headers or the body."""

    def do_GET(self) -> None:  # noqa: N802
        self._reject()

    def do_POST(self) -> None:  # noqa: N802
        length = self.headers.get("Content-Length", "0")
        try:
            size = int(length)
        except ValueError:
            size = 0
        if size > 0:
            remaining = min(size, 1_000_000)
            while remaining:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        self._reject()

    def _reject(self) -> None:
        body = b'{"error":"fake rate cap"}\n'
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        del fmt, args
        sys.stderr.write("fake-webhook: request handled\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake-webhook")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("port must be from 1 to 65535", file=sys.stderr)
        return 2
    work = args.dir if args.dir is not None else _default_dir()
    work.mkdir(parents=True, exist_ok=True)
    cert = work / "cert.pem"
    key = work / "key.pem"
    bundle = work / "bundle.pem"
    if not _certificate(cert, key):
        return 1
    if not _bundle(cert, bundle):
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    url = f"https://127.0.0.1:{args.port}/hook"
    print(f"URL: {url}")
    print(f"bundle: {bundle}")
    print("Trust this bundle for the check only:")
    print(f"  systemctl --user set-environment SSL_CERT_FILE={bundle}")
    print("  systemctl --user restart tetherbot")
    print("When finished:")
    print("  systemctl --user unset-environment SSL_CERT_FILE")
    print("  systemctl --user restart tetherbot")
    print("This server returns HTTP 400 and does not print the request.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def _default_dir() -> Path:
    runtime = os_runtime()
    if runtime is not None:
        return runtime / "tetherbot-fake-webhook"
    return Path.home() / ".local" / "state" / "tetherbot" / "fake-webhook"


def os_runtime() -> Path | None:
    import os

    value = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if not value:
        return None
    return Path(value)


def _certificate(cert: Path, key: Path) -> bool:
    if cert.is_file() and key.is_file():
        return True
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-nodes",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("openssl could not write a local certificate", file=sys.stderr)
        return False
    return True


def _bundle(cert: Path, bundle: Path) -> bool:
    cafile = ssl.get_default_verify_paths().cafile
    if not cafile:
        print("the system certificate store was not found", file=sys.stderr)
        return False
    system = Path(cafile)
    if not system.is_file():
        print("the system certificate store was not found", file=sys.stderr)
        return False
    bundle.write_bytes(system.read_bytes() + b"\n" + cert.read_bytes())
    bundle.chmod(0o600)
    return True


if __name__ == "__main__":
    raise SystemExit(main())

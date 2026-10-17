#!/usr/bin/env bash
# Install TetherBot user-session templates. Safe to run more than once.
# Does not enable or start the service, and never reads a secret.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install.sh

Copy the user unit, D-Bus activation file, and example config into the
per-user directories. Does not enable or start anything.

The bridge process exists, but this installer does not place a launcher.
The unit ExecStart is still /bin/false, so D-Bus activation does not
start it. --enable is refused.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--enable" ]]; then
  echo "tetherbot: refusing --enable. The unit does not launch the bridge yet." >&2
  exit 1
fi
if [[ $# -gt 0 ]]; then
  echo "tetherbot: unknown argument: $1" >&2
  usage >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${DATA_HOME}/tetherbot/app"
UNIT_DIR="${CONFIG_HOME}/systemd/user"
DBUS_DIR="${DATA_HOME}/dbus-1/services"
CONFIG_DIR="${CONFIG_HOME}/tetherbot"

install -d "${BIN_DIR}" "${APP_DIR}" "${UNIT_DIR}" "${DBUS_DIR}" "${CONFIG_DIR}"
install -m 0644 "${ROOT}/systemd/tetherbot.service" "${UNIT_DIR}/tetherbot.service"
install -m 0644 "${ROOT}/systemd/io.github.grokkinggrok.TetherBot1.service" \
  "${DBUS_DIR}/io.github.grokkinggrok.TetherBot1.service"
printf '%s\n' 'TetherBot scaffold. The launcher is not installed yet.' \
  > "${APP_DIR}/SCAFFOLD"

if [[ ! -e "${CONFIG_DIR}/config.toml" ]]; then
  install -m 0600 "${ROOT}/data/config.example.toml" "${CONFIG_DIR}/config.toml"
  echo "Wrote ${CONFIG_DIR}/config.toml"
else
  echo "Left existing ${CONFIG_DIR}/config.toml in place"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "warning: python3 is not on PATH" >&2
else
  py_version="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  echo "python3 ${py_version}"
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)'; then
    echo "warning: Python 3.13+ is the target runtime" >&2
  fi
  if ! python3 -c 'import gi' >/dev/null 2>&1; then
    echo "warning: PyGObject (gi) is not importable. Install the OS package python3-gobject." >&2
  elif ! python3 -c 'import gi; gi.require_version("Secret", "1"); from gi.repository import Secret' >/dev/null 2>&1; then
    echo "warning: Secret-1 typelib is not importable. Install the OS libsecret typelib." >&2
  fi
fi
if ! command -v git >/dev/null 2>&1; then
  echo "warning: git is not on PATH" >&2
fi
if command -v gnome-shell >/dev/null 2>&1; then
  gnome-shell --version || true
else
  echo "warning: gnome-shell is not on PATH (the extension targets GNOME Shell 50)" >&2
fi

if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user is-system-running >/dev/null 2>&1; then
  systemctl --user daemon-reload
  echo "Reloaded the user systemd manager."
else
  echo "warning: no user systemd manager. Skipped daemon-reload." >&2
fi

echo "Installed TetherBot templates. The service was not enabled or started."

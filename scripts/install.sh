#!/usr/bin/env bash
# Install TetherBot for the current user. Safe to run more than once.
# Does not read a secret. Without --enable, nothing is started.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [--enable]

Copy the bridge into the per-user app directory, install launchers, the
user unit, and the D-Bus activation file, and write config.toml when it
is missing.

  ~/.local/share/tetherbot/app/tetherbot/
  ~/.local/bin/tetherbot
  ~/.local/bin/tetherbotctl
  ~/.local/bin/git-credential-tetherbot

--enable runs: systemctl --user enable --now tetherbot.service
EOF
}

enable=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --enable)
      enable=1
      ;;
    *)
      echo "tetherbot: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${DATA_HOME}/tetherbot/app"
UNIT_DIR="${CONFIG_HOME}/systemd/user"
DBUS_DIR="${DATA_HOME}/dbus-1/services"
CONFIG_DIR="${CONFIG_HOME}/tetherbot"
LAUNCHER="${BIN_DIR}/tetherbot"

copy_python_package() {
  local src="$1"
  local dest="$2"
  local list file rel parent
  list="$(mktemp)"
  find "${src}" -type f -name '*.py' > "${list}"
  install -d "${dest}"
  while IFS= read -r file; do
    if [[ -z "${file}" ]]; then
      continue
    fi
    rel="${file#"${src}/"}"
    parent="$(dirname "${rel}")"
    install -d "${dest}/${parent}"
    install -m 0644 "${file}" "${dest}/${rel}"
  done < "${list}"
  rm -f "${list}"
}

write_dbus_service() {
  local src="$1"
  local dest="$2"
  local launcher="$3"
  local tmp line
  tmp="$(mktemp)"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == 'Exec=@TETHERBOT_LAUNCHER@' ]]; then
      printf 'Exec=%s\n' "${launcher}"
    else
      printf '%s\n' "${line}"
    fi
  done < "${src}" > "${tmp}"
  install -m 0644 "${tmp}" "${dest}"
  rm -f "${tmp}"
}

install -d "${BIN_DIR}" "${APP_DIR}" "${UNIT_DIR}" "${DBUS_DIR}" "${CONFIG_DIR}"
rm -rf "${APP_DIR}/tetherbot"
rm -f "${APP_DIR}/SCAFFOLD"
copy_python_package "${ROOT}/bridge/tetherbot" "${APP_DIR}/tetherbot"
install -m 0644 "${ROOT}/data/io.github.grokkinggrok.TetherBot1.xml" \
  "${APP_DIR}/tetherbot/io.github.grokkinggrok.TetherBot1.xml"
install -m 0755 "${ROOT}/scripts/launchers/tetherbot" "${BIN_DIR}/tetherbot"
install -m 0755 "${ROOT}/scripts/launchers/tetherbotctl" "${BIN_DIR}/tetherbotctl"
install -m 0755 "${ROOT}/scripts/launchers/git-credential-tetherbot" \
  "${BIN_DIR}/git-credential-tetherbot"
install -m 0644 "${ROOT}/systemd/tetherbot.service" "${UNIT_DIR}/tetherbot.service"
write_dbus_service "${ROOT}/systemd/io.github.grokkinggrok.TetherBot1.service" \
  "${DBUS_DIR}/io.github.grokkinggrok.TetherBot1.service" "${LAUNCHER}"

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
  shell_version="$(gnome-shell --version 2>/dev/null || true)"
  if [[ -n "${shell_version}" ]]; then
    echo "${shell_version}"
  fi
  if [[ ! "${shell_version}" =~ GNOME\ Shell\ 50([.[:space:]]|$) ]]; then
    echo "warning: the extension targets GNOME Shell 50" >&2
  fi
else
  echo "warning: gnome-shell is not on PATH (the extension targets GNOME Shell 50)" >&2
fi

user_systemd=0
if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user show-environment >/dev/null 2>&1; then
  user_systemd=1
fi
if [[ "${user_systemd}" -eq 1 ]]; then
  systemctl --user daemon-reload
  echo "Reloaded the user systemd manager."
else
  echo "warning: no user systemd manager. Skipped daemon-reload." >&2
fi

if [[ "${enable}" -eq 1 ]]; then
  if [[ "${user_systemd}" -ne 1 ]]; then
    echo "tetherbot: --enable needs a user systemd manager." >&2
    exit 1
  fi
  systemctl --user enable --now tetherbot.service
  echo "Enabled and started tetherbot.service."
else
  echo "Installed TetherBot. The service was not enabled or started."
fi
echo "Launchers: ${BIN_DIR}/tetherbot ${BIN_DIR}/tetherbotctl ${BIN_DIR}/git-credential-tetherbot"

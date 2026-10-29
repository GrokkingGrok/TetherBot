#!/usr/bin/env bash
# Remove the TetherBot files scripts/install.sh and scripts/install-extension.sh place.
# Safe to run more than once. Does not delete secret-service items.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/uninstall.sh [--purge] [--yes]

Removes the user unit, D-Bus activation files, the window desktop file,
the app copy, launchers, and the extension directory. Leaves config,
state, and repository clones in place unless --purge is given.

--purge also removes the config directory, the state directory, and
~/.local/share/tetherbot (including clones).
On a terminal it asks first. Without a terminal, pass --yes.
Keyring items are never deleted.
EOF
}

purge=0
assume_yes=0
for arg in "$@"; do
  case "${arg}" in
    -h|--help)
      usage
      exit 0
      ;;
    --purge) purge=1 ;;
    --yes) assume_yes=1 ;;
    *)
      echo "tetherbot: unknown argument: ${arg}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${DATA_HOME}/tetherbot/app"
DATA_DIR="${DATA_HOME}/tetherbot"
UNIT_DIR="${CONFIG_HOME}/systemd/user"
UNIT_PATH="${UNIT_DIR}/tetherbot.service"
WINDOW_UNIT_PATH="${UNIT_DIR}/tetherbot-window.service"
DEFAULT_WANTS="${UNIT_DIR}/default.target.wants/tetherbot.service"
SESSION_WANTS="${UNIT_DIR}/graphical-session.target.wants/tetherbot.service"
DBUS_PATH="${DATA_HOME}/dbus-1/services/io.github.grokkinggrok.TetherBot1.service"
WINDOW_DBUS_PATH="${DATA_HOME}/dbus-1/services/io.github.grokkinggrok.TetherBot.service"
DESKTOP_PATH="${DATA_HOME}/applications/io.github.grokkinggrok.TetherBot.desktop"
ICON_PATH="${DATA_HOME}/icons/hicolor/scalable/apps/io.github.grokkinggrok.TetherBot.svg"
ICON_SYMBOLIC_PATH="${DATA_HOME}/icons/hicolor/symbolic/apps/io.github.grokkinggrok.TetherBot-symbolic.svg"
CONFIG_DIR="${CONFIG_HOME}/tetherbot"
STATE_DIR="${STATE_HOME}/tetherbot"
EXT_DIR="${DATA_HOME}/gnome-shell/extensions/tetherbot@grokkinggrok.github.io"

if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user disable --now tetherbot.service >/dev/null 2>&1 || true
  systemctl --user stop tetherbot-window.service >/dev/null 2>&1 || true
fi
rm -f "${UNIT_PATH}" "${WINDOW_UNIT_PATH}" "${DEFAULT_WANTS}" "${SESSION_WANTS}" \
  "${DBUS_PATH}" "${WINDOW_DBUS_PATH}" "${DESKTOP_PATH}" \
  "${ICON_PATH}" "${ICON_SYMBOLIC_PATH}" \
  "${BIN_DIR}/tetherbot" "${BIN_DIR}/tetherbotctl" "${BIN_DIR}/git-credential-tetherbot" \
  "${BIN_DIR}/tetherbot-window"
rm -rf "${APP_DIR}"
rm -f "${DATA_DIR}/SCAFFOLD"
if [[ -d "${EXT_DIR}" ]]; then
  rm -rf "${EXT_DIR}"
fi
if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

if [[ "${purge}" -eq 1 ]]; then
  if [[ "${assume_yes}" -ne 1 ]]; then
    if [[ -t 0 ]]; then
      printf 'Delete %s, %s, and %s? Keyring items are kept. [y/N] ' \
        "${CONFIG_DIR}" "${STATE_DIR}" "${DATA_DIR}"
      read -r answer
      if [[ "${answer}" != "y" && "${answer}" != "Y" ]]; then
        echo "Kept config, state, and clones."
        echo "Removed TetherBot files. Keyring items were not touched."
        exit 0
      fi
    else
      echo "tetherbot: --purge needs confirmation. Re-run with --yes." >&2
      echo "tetherbot: config and state were kept. Installed files were removed." >&2
      exit 1
    fi
  fi
  rm -rf "${CONFIG_DIR}" "${STATE_DIR}" "${DATA_DIR}"
  echo "Removed config, state, and clones. Keyring items were not touched."
fi

echo "Removed TetherBot files. Keyring items were not touched."

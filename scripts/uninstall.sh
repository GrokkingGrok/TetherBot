#!/usr/bin/env bash
# Remove TetherBot user-session templates. Safe to run more than once.
# Does not touch the secret service.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/uninstall.sh [--purge] [--yes]

Removes the user unit, D-Bus activation file, and app copy.
Leaves config and state in place unless --purge is given.

--purge also removes the config and state directories.
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

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
APP_DIR="${DATA_HOME}/tetherbot"
UNIT_PATH="${CONFIG_HOME}/systemd/user/tetherbot.service"
DBUS_PATH="${DATA_HOME}/dbus-1/services/io.github.grokkinggrok.TetherBot1.service"
CONFIG_DIR="${CONFIG_HOME}/tetherbot"
STATE_DIR="${STATE_HOME}/tetherbot"

if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user is-system-running >/dev/null 2>&1; then
  systemctl --user disable --now tetherbot.service >/dev/null 2>&1 || true
fi
rm -f "${UNIT_PATH}" "${DBUS_PATH}"
rm -rf "${APP_DIR}"
if command -v systemctl >/dev/null 2>&1 \
  && systemctl --user is-system-running >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

if [[ "${purge}" -eq 1 ]]; then
  if [[ "${assume_yes}" -ne 1 ]]; then
    if [[ -t 0 ]]; then
      printf 'Delete %s and %s? Keyring items are kept. [y/N] ' \
        "${CONFIG_DIR}" "${STATE_DIR}"
      read -r answer
      if [[ "${answer}" != "y" && "${answer}" != "Y" ]]; then
        echo "Kept config and state."
        echo "Removed TetherBot templates."
        exit 0
      fi
    else
      echo "tetherbot: --purge needs confirmation. Re-run with --yes." >&2
      echo "tetherbot: config and state were kept. Templates were removed." >&2
      exit 1
    fi
  fi
  rm -rf "${CONFIG_DIR}" "${STATE_DIR}"
  echo "Removed config and state. Keyring items were not touched."
fi

echo "Removed TetherBot templates."

#!/usr/bin/env bash
# Install the GNOME Shell extension for the current user.
# Safe to run more than once. Does not enable the extension and does not
# read a secret. On Wayland, log out and back in before enabling it.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install-extension.sh

Copy the extension into:
  ~/.local/share/gnome-shell/extensions/tetherbot@grokkinggrok.github.io

Compiles gschemas when extension/schemas exists. Does not enable the
extension. Log out and log back in (Wayland reloads shell code that way),
then enable UUID tetherbot@grokkinggrok.github.io.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "tetherbot: unknown argument: $1" >&2
  usage >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="tetherbot@grokkinggrok.github.io"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
DEST="${DATA_HOME}/gnome-shell/extensions/${UUID}"
case "${DEST}" in
  */gnome-shell/extensions/tetherbot@grokkinggrok.github.io) ;;
  *)
    echo "tetherbot: refusing to replace ${DEST}" >&2
    exit 1
    ;;
esac

rm -rf "${DEST}"
install -d "${DEST}"
for name in extension.js view.js prefs.js stylesheet.css metadata.json \
  io.github.grokkinggrok.TetherBot1.xml; do
  install -m 0644 "${ROOT}/extension/${name}" "${DEST}/${name}"
done
if [[ -d "${ROOT}/extension/icons" ]]; then
  install -d "${DEST}/icons"
  for icon in "${ROOT}/extension/icons/"*.svg; do
    if [[ -f "${icon}" ]]; then
      install -m 0644 "${icon}" "${DEST}/icons/$(basename "${icon}")"
    fi
  done
fi

schema_dir="${ROOT}/extension/schemas"
if [[ -d "${schema_dir}" ]]; then
  found=0
  for schema in "${schema_dir}"/*.xml; do
    if [[ -f "${schema}" ]]; then
      found=1
      break
    fi
  done
  if [[ "${found}" -eq 1 ]]; then
    install -d "${DEST}/schemas"
    for schema in "${schema_dir}"/*.xml; do
      if [[ -f "${schema}" ]]; then
        install -m 0644 "${schema}" "${DEST}/schemas/$(basename "${schema}")"
      fi
    done
    if command -v glib-compile-schemas >/dev/null 2>&1; then
      glib-compile-schemas "${DEST}/schemas"
    else
      echo "warning: glib-compile-schemas is not on PATH" >&2
    fi
  fi
fi

echo "Installed ${UUID} to ${DEST}"
echo "Log out and log back in before enabling the extension."
echo "Wayland does not reload GNOME Shell code until you do."
echo "Then enable UUID ${UUID}."

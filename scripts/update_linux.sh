#!/usr/bin/env bash
set -euo pipefail
if [[ ! -d .git ]]; then
  echo "Run this updater from a LumenDesk Git checkout." >&2
  exit 1
fi
git pull --ff-only
exec "$(dirname "$0")/build_appimage.sh"

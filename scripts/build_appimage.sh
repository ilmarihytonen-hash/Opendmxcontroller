#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Build the AppImage on Ubuntu/Linux; AppImage cannot be produced natively on Windows." >&2
  exit 1
fi
if ! command -v cmake >/dev/null 2>&1; then
  echo "Install CMake, a C++17 compiler, and Python 3 before building." >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "Install curl to download the official linuxdeploy packaging tools." >&2
  exit 1
fi

TOOLS_DIR="$PWD/build/tools"
mkdir -p "$TOOLS_DIR"
if ! command -v linuxdeploy >/dev/null 2>&1; then
  curl --fail --location --silent --show-error \
    https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage \
    --output "$TOOLS_DIR/linuxdeploy"
  chmod +x "$TOOLS_DIR/linuxdeploy"
fi
export PATH="$TOOLS_DIR:$PATH"
export APPIMAGE_EXTRACT_AND_RUN=1

python3 -m venv build/venv
build/venv/bin/python -m pip install -r requirements.txt pyinstaller
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

APPDIR="$PWD/build/LumenDesk.AppDir"
mkdir -p dist
mkdir -p "$APPDIR/usr/bin"
build/venv/bin/python -m PyInstaller --noconfirm --clean --onefile \
  --name lumendesk --distpath "$APPDIR/usr/bin" \
  --add-binary "$PWD/build/liblumendesk_core.so:." \
  --hidden-import=mido.backends.rtmidi --hidden-import=rtmidi run.py
cp assets/AppRun "$APPDIR/AppRun"
cp assets/lumendesk.desktop "$APPDIR/lumendesk.desktop"
cp assets/lumendesk.svg "$APPDIR/lumendesk.svg"
build/venv/bin/python scripts/render_icon.py assets/lumendesk.svg build/lumendesk.png
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/lumendesk"
"$TOOLS_DIR/linuxdeploy" --appdir "$APPDIR" \
  --desktop-file assets/lumendesk.desktop \
  --icon-file build/lumendesk.png \
  --output appimage

APPIMAGE="$(find "$PWD" -maxdepth 1 -type f -iname '*.AppImage' -print -quit)"
if [[ -z "$APPIMAGE" ]]; then
  echo "linuxdeploy completed without producing an AppImage." >&2
  exit 1
fi
cp "$APPIMAGE" "$PWD/dist/LumenDesk-x86_64.AppImage"

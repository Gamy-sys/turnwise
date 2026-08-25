#!/usr/bin/env bash
# Build a Mac-installable Turnwise.app / .dmg
#
# Must be run on a Mac with:
#   - Python 3.10+
#   - Node 18+
#   - ffmpeg (brew install ffmpeg)
#   - Xcode CLT
#
# Usage (from ca-studio/):
#   ./scripts/build-mac.sh
#
# Output:
#   desktop/dist/Turnwise-*-arm64.dmg
#   desktop/dist/Turnwise-*-x64.dmg   (if building universal / both)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$HERE/frontend"
DESKTOP="$HERE/desktop"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "WARNING: This script is meant to run on macOS."
  echo "You can still prepare the Electron project; the .dmg must be built on a Mac."
fi

echo "[1/4] Building frontend…"
( cd "$FRONTEND" && npm install && npm run build )

echo "[2/4] Preparing desktop deps…"
( cd "$DESKTOP" && npm install )

# Optional icon conversion if iconutil / png exists
if [[ -f "$HERE/icons/turnwise.svg" && ! -f "$DESKTOP/build/icon.icns" ]]; then
  mkdir -p "$DESKTOP/build"
  if command -v rsvg-convert >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
    echo "[icon] converting SVG → .icns"
    TMP=$(mktemp -d)
    ICONSET="$TMP/Turnwise.iconset"
    mkdir -p "$ICONSET"
    for s in 16 32 64 128 256 512 1024; do
      rsvg-convert -w "$s" -h "$s" "$HERE/icons/turnwise.svg" -o "$ICONSET/icon_${s}x${s}.png"
    done
    cp "$ICONSET/icon_32x32.png" "$ICONSET/icon_16x16@2x.png"
    cp "$ICONSET/icon_64x64.png" "$ICONSET/icon_32x32@2x.png"
    cp "$ICONSET/icon_256x256.png" "$ICONSET/icon_128x128@2x.png"
    cp "$ICONSET/icon_512x512.png" "$ICONSET/icon_256x256@2x.png"
    cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET" -o "$DESKTOP/build/icon.icns"
    rm -rf "$TMP"
  else
    echo "[icon] skip (.icns needs rsvg-convert + iconutil on Mac). electron-builder will use a default icon."
  fi
fi

echo "[3/4] Packaging with electron-builder…"
( cd "$DESKTOP" && npm run dist:mac )

echo "[4/4] Done. Installers are in:"
ls -la "$DESKTOP/dist"/*.dmg 2>/dev/null || ls -la "$DESKTOP/dist" || true
echo
echo "Install: open the .dmg and drag Turnwise into Applications."
echo "First launch installs Python packages into ~/Library/Application Support/Turnwise — allow a few minutes."

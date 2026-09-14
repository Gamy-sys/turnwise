#!/usr/bin/env bash
# Build Turnwise.app / .dmg on macOS (native CPU arch only).
#
# Prerequisites:
#   - macOS with Xcode CLT
#   - Python 3.10+, Node 18+, ffmpeg  (brew install python@3.12 node ffmpeg)
#
# Usage (from the Turnwise folder):
#   ./scripts/build-mac.sh
# Or double-click:  Install Turnwise.command
#
# Output:
#   desktop/dist/Turnwise-*.dmg
#   desktop/dist/mac*/Turnwise.app
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$HERE/frontend"
DESKTOP="$HERE/desktop"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: build-mac.sh must run on a Mac."
  echo "On Linux, create a sendable package with:"
  echo "  ./scripts/make-mac-installer-zip.sh"
  exit 1
fi

for cmd in python3 node npm ffmpeg; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: '$cmd' not found."
    echo "Install with:  brew install python@3.12 node ffmpeg"
    exit 1
  fi
done

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) EB_ARCH="--arm64" ;;
  x86_64) EB_ARCH="--x64" ;;
  *) EB_ARCH="" ;;
esac

echo "[1/4] Building frontend…"
( cd "$FRONTEND" && npm install && npm run build )

if [[ ! -f "$FRONTEND/dist/index.html" ]]; then
  echo "ERROR: frontend build did not produce dist/index.html"
  exit 1
fi

echo "[2/4] Preparing desktop deps…"
( cd "$DESKTOP" && npm install )

# Optional Dock icon
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
    echo "[icon] skip (.icns needs: brew install librsvg). Using default Electron icon."
  fi
fi

echo "[3/4] Packaging Turnwise.app + .dmg for $ARCH…"
( cd "$DESKTOP" && npx electron-builder --mac dmg $EB_ARCH )

echo "[4/4] Done."
echo
ls -lah "$DESKTOP/dist"/*.dmg 2>/dev/null || true
find "$DESKTOP/dist" -name "Turnwise.app" -type d 2>/dev/null | head -5 || true
echo
echo "Install: open the .dmg and drag Turnwise into Applications."
echo "First launch installs Python packages under"
echo "  ~/Library/Application Support/Turnwise"
echo "(allow several minutes)."

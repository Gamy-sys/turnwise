#!/usr/bin/env bash
# Create a real double-clickable Turnwise.app (no Electron).
# The app starts the local server and opens the UI in the default browser.
#
# Usage (from Turnwise folder, on a Mac):
#   ./scripts/create-mac-app.sh
#   ./scripts/create-mac-app.sh ~/Applications
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/Applications}"
SUPPORT="$HOME/Library/Application Support/Turnwise"
APP="$DEST/Turnwise.app"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: create-mac-app.sh only runs on macOS."
  exit 1
fi

mkdir -p "$SUPPORT" "$DEST"
echo "$HERE" > "$SUPPORT/install_path.txt"

# Optional icon
ICON_SRC=""
if [[ -f "$HERE/desktop/build/icon.icns" ]]; then
  ICON_SRC="$HERE/desktop/build/icon.icns"
elif command -v rsvg-convert >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1 \
    && [[ -f "$HERE/icons/turnwise.svg" ]]; then
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
  iconutil -c icns "$ICONSET" -o "$TMP/icon.icns"
  ICON_SRC="$TMP/icon.icns"
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Turnwise</string>
  <key>CFBundleDisplayName</key><string>Turnwise</string>
  <key>CFBundleIdentifier</key><string>app.turnwise.launcher</string>
  <key>CFBundleVersion</key><string>0.3.0</string>
  <key>CFBundleShortVersionString</key><string>0.3.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Turnwise</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

if [[ -n "$ICON_SRC" && -f "$ICON_SRC" ]]; then
  cp "$ICON_SRC" "$APP/Contents/Resources/AppIcon.icns"
fi

cat > "$APP/Contents/MacOS/Turnwise" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
SUPPORT="$HOME/Library/Application Support/Turnwise"
LOG="$SUPPORT/launch.log"
mkdir -p "$SUPPORT"

exec >>"$LOG" 2>&1
echo "==== $(date) Turnwise launch ===="

ROOT=""
if [[ -f "$SUPPORT/install_path.txt" ]]; then
  ROOT="$(tr -d '\r\n' < "$SUPPORT/install_path.txt")"
fi
# Fallbacks if the install path file is missing
if [[ -z "$ROOT" || ! -x "$ROOT/run.sh" ]]; then
  for cand in \
    "$HOME/Turnwise" \
    "$HOME/Applications/Turnwise-Mac-Installer" \
    "$HOME/Downloads/Turnwise-Mac-Installer" \
    "$HOME/Desktop/Turnwise-Mac-Installer"
  do
    if [[ -x "$cand/run.sh" ]]; then
      ROOT="$cand"
      echo "$ROOT" > "$SUPPORT/install_path.txt"
      break
    fi
  done
fi

if [[ -z "$ROOT" || ! -x "$ROOT/run.sh" ]]; then
  osascript -e 'display dialog "Turnwise install folder not found.\n\nRe-run Install Turnwise.command from the unzipped folder." buttons {"OK"} default button 1 with title "Turnwise"'
  exit 1
fi

cd "$ROOT"
chmod +x "$ROOT/run.sh" 2>/dev/null || true

# If already up, just open the browser
for port in 8000 8001 8002 8003; do
  if curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    open "http://127.0.0.1:$port/"
    exit 0
  fi
done

# Start server in background; open browser when ready
"$ROOT/run.sh" >>"$LOG" 2>&1 &
SERVER_PID=$!
echo "server pid=$SERVER_PID"

URL=""
for i in $(seq 1 180); do
  for port in 8000 8001 8002 8003 8004 8005; do
    if curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1; then
      URL="http://127.0.0.1:$port/"
      break 2
    fi
  done
  sleep 1
done

if [[ -z "$URL" ]]; then
  osascript -e 'display dialog "Turnwise started but the UI did not become ready in time.\n\nCheck:\n~/Library/Application Support/Turnwise/launch.log" buttons {"OK"} default button 1 with title "Turnwise"'
  exit 1
fi

open "$URL"
# Keep a tiny helper alive so the Dock icon does not vanish immediately;
# the real work is the background run.sh / uvicorn process.
sleep 2
exit 0
LAUNCH
chmod +x "$APP/Contents/MacOS/Turnwise"

# Also keep a copy next to the install for convenience
LOCAL_APP="$HERE/Turnwise.app"
rm -rf "$LOCAL_APP"
cp -R "$APP" "$LOCAL_APP"

echo "Created: $APP"
echo "Also:    $LOCAL_APP"
echo "Install path saved to: $SUPPORT/install_path.txt"
echo
echo "Open Turnwise from Applications / Launchpad, or:"
echo "  open \"$APP\""

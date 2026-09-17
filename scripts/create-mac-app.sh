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

# Prefer the system Applications folder when writable; else ~/Applications.
# Finder's sidebar "Applications" is /Applications — many people miss ~/Applications.
if [[ "$DEST" == "$HOME/Applications" ]]; then
  if mkdir -p /Applications 2>/dev/null && [[ -w /Applications ]]; then
    DEST="/Applications"
    APP="$DEST/Turnwise.app"
  fi
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

echo "==== $(date) Turnwise launch ====" >>"$LOG"

ROOT=""
if [[ -f "$SUPPORT/install_path.txt" ]]; then
  ROOT="$(tr -d '\r\n' < "$SUPPORT/install_path.txt")"
fi
if [[ -z "$ROOT" || ! -x "$ROOT/run.sh" ]]; then
  for cand in \
    "$HOME/Turnwise" \
    "$HOME/Applications/Turnwise-Mac-Installer" \
    "$HOME/Downloads/Turnwise-Mac-Installer" \
    "$HOME/Downloads/Turnwise-Mac-Installer-2" \
    "$HOME/Desktop/Turnwise-Mac-Installer" \
    "$HOME/Desktop/Turnwise-Mac-Installer-2"
  do
    if [[ -x "$cand/run.sh" ]]; then
      ROOT="$cand"
      echo "$ROOT" > "$SUPPORT/install_path.txt"
      break
    fi
  done
fi

# Also search Downloads for any Turnwise-Mac-Installer*
if [[ -z "$ROOT" || ! -x "$ROOT/run.sh" ]]; then
  found="$(find "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" -maxdepth 2 -name 'run.sh' -path '*Turnwise*' 2>/dev/null | head -1 || true)"
  if [[ -n "$found" ]]; then
    ROOT="$(cd "$(dirname "$found")" && pwd)"
    echo "$ROOT" > "$SUPPORT/install_path.txt"
  fi
fi

if [[ -z "$ROOT" || ! -x "$ROOT/run.sh" ]]; then
  osascript -e 'display dialog "Turnwise install folder not found.\n\nRe-run Install Turnwise.command from the unzipped folder." buttons {"OK"} default button 1 with title "Turnwise"' >>"$LOG" 2>&1
  exit 1
fi

cd "$ROOT"
chmod +x "$ROOT/run.sh" "$ROOT/Start Turnwise.command" 2>/dev/null || true
echo "ROOT=$ROOT" >>"$LOG"

# If already up, just open the browser
for port in 8000 8001 8002 8003 8004 8005; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    open "http://127.0.0.1:$port/"
    exit 0
  fi
done

osascript >>"$LOG" 2>&1 <<EOF || true
display notification "Starting server — first open can take 1–3 minutes…" with title "Turnwise"
EOF

# Start server in the background; mirror output to launch.log
(
  cd "$ROOT"
  export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
  exec ./run.sh
) >>"$LOG" 2>&1 &
SERVER_PID=$!
echo "server pid=$SERVER_PID" >>"$LOG"

# Wait up to 15 minutes (900s). First Python/torch import on Mac can be slow.
URL=""
for i in $(seq 1 900); do
  if [[ -f "$ROOT/data/last_port.txt" ]]; then
    port="$(tr -d '\r\n' < "$ROOT/data/last_port.txt")"
    if [[ -n "$port" ]] && curl -fsS --max-time 2 "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      URL="http://127.0.0.1:${port}/"
      break
    fi
  fi
  for port in 8000 8001 8002 8003 8004 8005; do
    if curl -fsS --max-time 2 "http://127.0.0.1:$port/" >/dev/null 2>&1; then
      URL="http://127.0.0.1:$port/"
      break 2
    fi
  done
  # If the background process died, stop waiting
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "server process exited early" >>"$LOG"
    break
  fi
  if (( i == 30 || i == 60 || i == 120 || i == 180 || i == 300 )); then
    osascript >>"$LOG" 2>&1 <<EOF || true
display notification "Still starting… ${i}s" with title "Turnwise"
EOF
  fi
  sleep 1
done

if [[ -n "$URL" ]]; then
  echo "ready $URL" >>"$LOG"
  open "$URL"
  osascript >>"$LOG" 2>&1 <<EOF || true
display notification "Turnwise is ready" with title "Turnwise"
EOF
  sleep 2
  exit 0
fi

# Failed — show log + offer Terminal fallback
echo "timeout / failed" >>"$LOG"
TAIL="$(tail -n 40 "$LOG" 2>/dev/null | sed 's/"/\\"/g' | tr '\n' ' ' | cut -c1-400)"
BTN="$(osascript <<EOF
try
  display dialog "Turnwise did not become ready in time.

Open the log, or start it in Terminal (you will see progress).

Last log lines:
$TAIL" buttons {"Open Log", "Start in Terminal", "Cancel"} default button "Start in Terminal" with title "Turnwise"
return button returned of result
on error
  return "Cancel"
end try
EOF
)"

case "$BTN" in
  "Open Log")
    open -a TextEdit "$LOG" 2>/dev/null || open "$LOG"
    ;;
  "Start in Terminal")
    # Open a real Terminal window so the friend can see errors
    osascript <<EOF
tell application "Terminal"
  activate
  do script "export PATH=\"/opt/homebrew/bin:/usr/local/bin:\$PATH\"; cd \"$ROOT\"; chmod +x ./run.sh \"./Start Turnwise.command\" 2>/dev/null; \"./Start Turnwise.command\""
end tell
EOF
    ;;
esac
exit 1
LAUNCH
chmod +x "$APP/Contents/MacOS/Turnwise"

# Also keep a copy next to the install for convenience
LOCAL_APP="$HERE/Turnwise.app"
rm -rf "$LOCAL_APP"
cp -R "$APP" "$LOCAL_APP"

# Put a copy on the Desktop so it is impossible to miss
DESKTOP_APP="$HOME/Desktop/Turnwise.app"
rm -rf "$DESKTOP_APP"
cp -R "$APP" "$DESKTOP_APP" 2>/dev/null || true

# Remember exact path for the installer success message
echo "$APP" > "$SUPPORT/app_path.txt"

echo "Created: $APP"
echo "Also:    $LOCAL_APP"
if [[ -d "$DESKTOP_APP" ]]; then
  echo "Desktop: $DESKTOP_APP"
fi
echo "Install path saved to: $SUPPORT/install_path.txt"
echo
echo "Open Turnwise from Applications / Launchpad / Desktop, or:"
echo "  open \"$APP\""

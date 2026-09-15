#!/bin/bash
# Install Turnwise — double-click this file on a Mac.
# Builds Turnwise.app / .dmg, then opens the installer.
#
# Always leaves BUILD-LOG.txt in this folder so errors are not lost
# when Terminal closes.
set +e
set -u

cd "$(dirname "$0")"
ROOT="$(pwd)"
LOG="$ROOT/BUILD-LOG.txt"

# macOS Terminal often starts with a tiny PATH; pull in Homebrew.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

exec > >(tee "$LOG") 2>&1

pause() {
  echo
  echo "Press Enter to close this window."
  read -r _ || true
}

clear 2>/dev/null || true
echo "============================================"
echo "  Turnwise — Mac app installer"
echo "============================================"
echo
echo "This builds a Turnwise icon for Applications."
echo
echo "Folder: $ROOT"
echo "Log:    $LOG"
echo
echo "IMPORTANT: the .dmg will appear inside THIS folder at:"
echo "  $ROOT/desktop/dist/"
echo "(that is NOT your Mac Desktop — it is the 'desktop' folder"
echo " inside Turnwise, where the Electron app lives.)"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This installer only runs on macOS."
  pause
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: Homebrew is not installed."
  echo "Install from https://brew.sh then run this file again."
  echo
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  pause
  exit 1
fi

echo "[check] Xcode Command Line Tools…"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installing Xcode CLT (a system dialog may appear)…"
  xcode-select --install || true
  echo "After CLT finishes installing, double-click this file again."
  pause
  exit 1
fi

echo "[check] python3 / node / npm / ffmpeg…"
MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python@3.12")
command -v node >/dev/null 2>&1 || MISSING+=("node")
command -v npm >/dev/null 2>&1 || MISSING+=("node")
command -v ffmpeg >/dev/null 2>&1 || MISSING+=("ffmpeg")
# de-dupe
if [[ ${#MISSING[@]} -gt 0 ]]; then
  # shellcheck disable=SC2207
  MISSING=($(printf '%s\n' "${MISSING[@]}" | awk '!a[$0]++'))
  echo "Installing: ${MISSING[*]}"
  brew install "${MISSING[@]}"
  if [[ $? -ne 0 ]]; then
    echo "ERROR: brew install failed. See log above."
    open -R "$LOG" 2>/dev/null || true
    pause
    exit 1
  fi
fi

echo
echo "Versions:"
python3 --version 2>&1 || true
node --version 2>&1 || true
npm --version 2>&1 || true
ffmpeg -version 2>&1 | head -1 || true
echo

echo "[build] Creating Turnwise.app (5–15 minutes, needs internet)…"
echo
chmod +x "$ROOT/scripts/build-mac.sh" "$ROOT/run.sh" 2>/dev/null || true
"$ROOT/scripts/build-mac.sh"
BUILD_RC=$?

DMG=$(ls -t "$ROOT/desktop/dist"/Turnwise-*.dmg 2>/dev/null | head -1 || true)
APP=$(find "$ROOT/desktop/dist" -maxdepth 3 -name "Turnwise.app" -type d 2>/dev/null | head -1 || true)

echo
echo "============================================"
if [[ $BUILD_RC -eq 0 && -n "${DMG:-}" && -f "$DMG" ]]; then
  echo "  SUCCESS — .dmg is ready"
  echo "============================================"
  echo
  echo "File:"
  echo "  $DMG"
  echo
  echo "Opening it — drag Turnwise into Applications."
  open "$DMG"
  open "$ROOT/desktop/dist" 2>/dev/null || true
elif [[ $BUILD_RC -eq 0 && -n "${APP:-}" ]]; then
  echo "  SUCCESS — app built (no dmg, using .app)"
  echo "============================================"
  echo
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Turnwise.app"
  cp -R "$APP" "$HOME/Applications/Turnwise.app"
  echo "Copied to ~/Applications/Turnwise.app"
  open "$HOME/Applications"
else
  echo "  BUILD FAILED — no .dmg created"
  echo "============================================"
  echo
  echo "There is no desktop/dist yet because packaging did not finish."
  echo
  echo "Send your friend (or the developer) this file:"
  echo "  $LOG"
  echo
  echo "Quick workaround (browser mode, no icon needed):"
  echo "  1. Open Terminal"
  echo "  2. cd \"$ROOT\""
  echo "  3. ./run.sh"
  echo "  4. Open http://127.0.0.1:8000 in Safari/Chrome"
  echo
  open -R "$LOG" 2>/dev/null || open "$ROOT" 2>/dev/null || true
  pause
  exit 1
fi

echo
echo "First launch tip: if macOS blocks the app —"
echo "  Right-click Turnwise → Open → Open"
echo "First start installs Python packages (several minutes)."
echo
echo "Full log saved at: $LOG"
pause
exit 0

#!/bin/bash
# Install Turnwise — double-click this file on a Mac.
# It builds Turnwise.app / a .dmg, then opens the installer.
#
# You need internet the first time (downloads Node packages + Electron).
# Prerequisites (Homebrew): python@3.12, node, ffmpeg
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

# macOS Terminal often starts with a tiny PATH; pull in Homebrew.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

clear 2>/dev/null || true
echo "============================================"
echo "  Turnwise — Mac app installer"
echo "============================================"
echo
echo "This will build a Turnwise icon you can put in"
echo "Applications and open like any other Mac app."
echo
echo "Folder: $ROOT"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This installer only runs on macOS."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

need_brew=0
command -v brew >/dev/null 2>&1 || need_brew=1
if [[ $need_brew -eq 1 ]]; then
  echo "Homebrew is not installed."
  echo "Install it from https://brew.sh  then run this file again."
  echo
  echo "Or paste this in Terminal:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo
  echo "Press Enter to close."
  read -r _
  exit 1
fi

echo "[check] Xcode Command Line Tools…"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installing Xcode CLT (a system dialog may appear)…"
  xcode-select --install || true
  echo "After CLT finishes installing, double-click this file again."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

echo "[check] python3 / node / ffmpeg…"
MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python@3.12")
command -v node >/dev/null 2>&1 || MISSING+=("node")
command -v ffmpeg >/dev/null 2>&1 || MISSING+=("ffmpeg")
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "Installing: ${MISSING[*]}"
  brew install "${MISSING[@]}"
fi

echo
echo "[build] Creating Turnwise.app (this can take 5–15 minutes)…"
echo
chmod +x "$ROOT/scripts/build-mac.sh" "$ROOT/run.sh" 2>/dev/null || true
"$ROOT/scripts/build-mac.sh"

DMG=$(ls -t "$ROOT/desktop/dist"/Turnwise-*.dmg 2>/dev/null | head -1 || true)
APP=$(find "$ROOT/desktop/dist" -maxdepth 3 -name "Turnwise.app" -type d 2>/dev/null | head -1 || true)

echo
echo "============================================"
echo "  Build finished"
echo "============================================"
echo

if [[ -n "$DMG" && -f "$DMG" ]]; then
  echo "Installer disk image:"
  echo "  $DMG"
  echo
  echo "Opening it now — drag Turnwise into Applications."
  open "$DMG"
elif [[ -n "$APP" ]]; then
  echo "App bundle:"
  echo "  $APP"
  echo
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Turnwise.app"
  cp -R "$APP" "$HOME/Applications/Turnwise.app"
  echo "Copied to ~/Applications/Turnwise.app"
  open "$HOME/Applications"
else
  echo "Could not find the .dmg or .app. Check messages above."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

echo
echo "First launch: if macOS says the app is from an unidentified"
echo "developer — Right-click Turnwise → Open → Open."
echo "The first start installs Python packages (several minutes)."
echo
echo "Press Enter to close this window."
read -r _

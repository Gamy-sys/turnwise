#!/usr/bin/env bash
# Create a zip you can SEND to a Mac friend.
# They unzip it, double-click "Install Turnwise.command", and get a Dock/Applications icon.
#
# Usage (on Linux or Mac, from the Turnwise folder):
#   ./scripts/make-mac-installer-zip.sh
#   ./scripts/make-mac-installer-zip.sh ~/Desktop
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep '"version"' "$HERE/frontend/package.json" | head -1 | sed 's/.*"\([0-9.]*\)".*/\1/')"
STAMP="$(date +%Y%m%d)"
OUT_DIR="${1:-$HOME/Desktop}"
ZIP_NAME="Turnwise-Mac-Installer-${VERSION}-${STAMP}.zip"
STAGING="$(mktemp -d)"
ROOT="$STAGING/Turnwise-Mac-Installer"

echo "[1/4] Building frontend…"
if command -v npm >/dev/null 2>&1; then
  ( cd "$HERE/frontend" && npm install && npm run build )
else
  echo "ERROR: npm required to build the UI before packaging."
  exit 1
fi
if [[ ! -f "$HERE/frontend/dist/index.html" ]]; then
  echo "ERROR: frontend/dist missing after build"
  exit 1
fi

echo "[2/4] Staging Mac installer tree…"
mkdir -p "$ROOT"

# Friend-facing instructions (top of the folder)
cat > "$ROOT/START HERE.txt" <<'EOF'
Turnwise for Mac — make a clickable app icon
============================================

1. Unzip this folder (keep everything together).

2. Double-click:  Install Turnwise.command
   • If macOS blocks it: Right-click → Open → Open
   • A Terminal window opens and builds the app (5–15 min)

3. When it finishes, a .dmg opens — drag Turnwise into Applications.

4. Open Turnwise from Applications (or Launchpad / Spotlight).
   First launch downloads Python packages — wait a few minutes.

Need once on the Mac (Homebrew):
  brew install python@3.12 node ffmpeg

More detail: INSTALL.md
EOF

# Double-click installer
cp "$HERE/Install Turnwise.command" "$ROOT/"
chmod +x "$ROOT/Install Turnwise.command"

for f in run.sh desktop-launch.sh README.md INSTALL.md; do
  [[ -f "$HERE/$f" ]] && cp "$HERE/$f" "$ROOT/"
done
chmod +x "$ROOT/run.sh" "$ROOT/desktop-launch.sh" 2>/dev/null || true

mkdir -p "$ROOT/icons" "$ROOT/scripts" "$ROOT/desktop/build"
cp -a "$HERE/icons/." "$ROOT/icons/" 2>/dev/null || true
cp "$HERE/scripts/build-mac.sh" "$HERE/scripts/make-mac-installer-zip.sh" "$ROOT/scripts/" 2>/dev/null || true
chmod +x "$ROOT/scripts/"*.sh "$ROOT/Install Turnwise.command"

# Backend (no venv)
mkdir -p "$ROOT/backend"
for f in requirements.txt requirements-diarization.txt; do
  [[ -f "$HERE/backend/$f" ]] && cp "$HERE/backend/$f" "$ROOT/backend/"
done
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  "$HERE/backend/app/" "$ROOT/backend/app/"

# Frontend dist + sources (build-mac rebuilds; dist is a fallback)
mkdir -p "$ROOT/frontend"
cp "$HERE/frontend/package.json" "$HERE/frontend/package-lock.json" "$ROOT/frontend/"
cp "$HERE/frontend/vite.config.js" "$HERE/frontend/index.html" "$ROOT/frontend/"
rsync -a "$HERE/frontend/dist/" "$ROOT/frontend/dist/"
rsync -a --exclude='node_modules' "$HERE/frontend/src/" "$ROOT/frontend/src/"

# Electron shell
for f in main.js preload.js package.json package-lock.json; do
  [[ -f "$HERE/desktop/$f" ]] && cp "$HERE/desktop/$f" "$ROOT/desktop/"
done
[[ -f "$HERE/desktop/.gitignore" ]] && cp "$HERE/desktop/.gitignore" "$ROOT/desktop/"
[[ -f "$HERE/desktop/build/.gitkeep" ]] && cp "$HERE/desktop/build/.gitkeep" "$ROOT/desktop/build/"

echo "[3/4] Zipping…"
mkdir -p "$OUT_DIR"
( cd "$STAGING" && zip -r -q "$OUT_DIR/$ZIP_NAME" Turnwise-Mac-Installer )

# Keep execute bits for .command / scripts inside the zip (Info-ZIP attribute)
# Re-pack with stored permissions if zipinfo shows issues — chmod before zip is enough on Linux→Mac for .command often needs:
# friend still Right-click Open the first time.

rm -rf "$STAGING"
SIZE="$(du -h "$OUT_DIR/$ZIP_NAME" | cut -f1)"
echo
echo "[4/4] Done."
echo "Send this file to your friend:"
echo "  $OUT_DIR/$ZIP_NAME  ($SIZE)"
echo
echo "On their Mac: unzip → double-click Install Turnwise.command → drag to Applications."

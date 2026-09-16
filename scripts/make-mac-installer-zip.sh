#!/usr/bin/env bash
# Create a zip you can SEND to a Mac friend.
# They unzip → double-click Install Turnwise.command → get Turnwise.app in Applications.
#
# Usage:
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

cat > "$ROOT/START HERE.txt" <<'EOF'
Turnwise for Mac — clickable app icon
=====================================

1. Unzip this folder and KEEP it somewhere permanent
   (e.g. Documents/Turnwise). Do not delete it after install —
   the app icon launches from this folder.

2. Double-click:  Install Turnwise.command
   • If macOS blocks it: Right-click → Open → Open
   • Leave Terminal open until it says SUCCESS
   • First install can take 10–20 minutes (downloads Python + diarization)

3. When finished, Turnwise.app is in Applications / Launchpad.
   Double-click that icon anytime to start Turnwise.

4. Speaker diarization is ON by default (2 speakers).
   A Hugging Face token is already bundled for your install.

If install fails: send BUILD-LOG.txt from this folder.

Need once (Homebrew):
  brew install python@3.12 node ffmpeg
EOF

cp "$HERE/Install Turnwise.command" "$ROOT/"
chmod +x "$ROOT/Install Turnwise.command"

for f in run.sh desktop-launch.sh README.md INSTALL.md; do
  [[ -f "$HERE/$f" ]] && cp "$HERE/$f" "$ROOT/"
done
chmod +x "$ROOT/run.sh" "$ROOT/desktop-launch.sh" 2>/dev/null || true

mkdir -p "$ROOT/icons" "$ROOT/scripts" "$ROOT/packaging" "$ROOT/desktop/build"
cp -a "$HERE/icons/." "$ROOT/icons/" 2>/dev/null || true
cp "$HERE/scripts/create-mac-app.sh" \
   "$HERE/scripts/build-mac.sh" \
   "$HERE/scripts/make-mac-installer-zip.sh" \
   "$ROOT/scripts/" 2>/dev/null || true
chmod +x "$ROOT/scripts/"*.sh "$ROOT/Install Turnwise.command"

# Bundled HF token for diarization (private zip — not in public git)
if [[ -f "$HERE/packaging/friend-secrets.json" ]]; then
  cp "$HERE/packaging/friend-secrets.json" "$ROOT/packaging/"
elif [[ -f "$HERE/data/secrets.json" ]]; then
  # Extract HF token only from local secrets
  python3 - <<PY
import json
from pathlib import Path
src = json.loads(Path("$HERE/data/secrets.json").read_text())
out = {}
if src.get("hf_token"):
    out["hf_token"] = src["hf_token"]
Path("$ROOT/packaging/friend-secrets.json").write_text(json.dumps(out, indent=2) + "\n")
print("[secrets] packed hf_token for friend install")
PY
else
  echo "WARNING: no HF token found to bundle — friend will need to paste one in Settings"
fi

# Backend (no venv)
mkdir -p "$ROOT/backend"
for f in requirements.txt requirements-diarization.txt; do
  [[ -f "$HERE/backend/$f" ]] && cp "$HERE/backend/$f" "$ROOT/backend/"
done
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  "$HERE/backend/app/" "$ROOT/backend/app/"

# Frontend
mkdir -p "$ROOT/frontend"
cp "$HERE/frontend/package.json" "$HERE/frontend/package-lock.json" "$ROOT/frontend/"
cp "$HERE/frontend/vite.config.js" "$HERE/frontend/index.html" "$ROOT/frontend/"
rsync -a "$HERE/frontend/dist/" "$ROOT/frontend/dist/"
rsync -a --exclude='node_modules' "$HERE/frontend/src/" "$ROOT/frontend/src/"

# Keep desktop/ for optional Electron builds, but primary path is create-mac-app.sh
for f in main.js preload.js package.json package-lock.json; do
  [[ -f "$HERE/desktop/$f" ]] && cp "$HERE/desktop/$f" "$ROOT/desktop/"
done
[[ -f "$HERE/desktop/.gitignore" ]] && cp "$HERE/desktop/.gitignore" "$ROOT/desktop/"
[[ -f "$HERE/desktop/build/.gitkeep" ]] && cp "$HERE/desktop/build/.gitkeep" "$ROOT/desktop/build/"

echo "[3/4] Zipping…"
mkdir -p "$OUT_DIR"
( cd "$STAGING" && zip -r -q "$OUT_DIR/$ZIP_NAME" Turnwise-Mac-Installer )
rm -rf "$STAGING"
SIZE="$(du -h "$OUT_DIR/$ZIP_NAME" | cut -f1)"
echo
echo "[4/4] Done."
echo "Send this file to your friend:"
echo "  $OUT_DIR/$ZIP_NAME  ($SIZE)"
echo
echo "On their Mac: unzip → double-click Install Turnwise.command"
echo "→ Turnwise appears in Applications."

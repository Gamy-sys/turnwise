#!/usr/bin/env bash
# Build turnwise-release-*.zip for sharing (no venv, no user data, no node_modules).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep '"version"' "$HERE/frontend/package.json" | head -1 | sed 's/.*"\([0-9.]*\)".*/\1/')"
STAMP="$(date +%Y%m%d)"
OUT_DIR="${1:-$HOME/Desktop}"
ZIP_NAME="turnwise-${VERSION}-${STAMP}.zip"
STAGING="$(mktemp -d)"
ROOT="$STAGING/turnwise"

echo "[1/3] Building frontend (if npm available)…"
if command -v npm >/dev/null 2>&1 && [[ -f "$HERE/frontend/package.json" ]]; then
  ( cd "$HERE/frontend" && npm run build ) || echo "[warn] frontend build failed — using existing dist/"
else
  echo "[warn] npm not found — packaging existing frontend/dist/"
fi

if [[ ! -f "$HERE/frontend/dist/index.html" ]]; then
  echo "ERROR: frontend/dist/index.html missing. Run: cd frontend && npm install && npm run build"
  exit 1
fi

echo "[2/3] Staging files…"
mkdir -p "$ROOT"

copy_tree() {
  rsync -a --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.pytest_cache' "$1/" "$2/"
}

# Core launchers & docs
for f in run.sh desktop-launch.sh README.md INSTALL.md turnwise.desktop sample.mp3; do
  [[ -f "$HERE/$f" ]] && cp "$HERE/$f" "$ROOT/"
done
chmod +x "$ROOT/run.sh" "$ROOT/desktop-launch.sh" 2>/dev/null || true

mkdir -p "$ROOT/icons"
cp -a "$HERE/icons/." "$ROOT/icons/" 2>/dev/null || true

mkdir -p "$ROOT/scripts"
cp -a "$HERE/scripts/build-mac.sh" "$HERE/scripts/make-release-zip.sh" "$ROOT/scripts/" 2>/dev/null || true
chmod +x "$ROOT/scripts/"*.sh 2>/dev/null || true

# Backend (no venv)
mkdir -p "$ROOT/backend"
for f in requirements.txt requirements-diarization.txt; do
  [[ -f "$HERE/backend/$f" ]] && cp "$HERE/backend/$f" "$ROOT/backend/"
done
copy_tree "$HERE/backend/app" "$ROOT/backend/app"
for t in "$HERE/backend"/*.py; do
  [[ -f "$t" ]] && cp "$t" "$ROOT/backend/" || true
done

# Frontend: dist + source (friend can rebuild); no node_modules
mkdir -p "$ROOT/frontend"
cp "$HERE/frontend/package.json" "$HERE/frontend/package-lock.json" "$ROOT/frontend/" 2>/dev/null || true
[[ -f "$HERE/frontend/vite.config.js" ]] && cp "$HERE/frontend/vite.config.js" "$ROOT/frontend/"
[[ -f "$HERE/frontend/index.html" ]] && cp "$HERE/frontend/index.html" "$ROOT/frontend/"
copy_tree "$HERE/frontend/dist" "$ROOT/frontend/dist"
copy_tree "$HERE/frontend/src" "$ROOT/frontend/src"

# Desktop Mac wrapper (no node_modules / no dist artifacts)
mkdir -p "$ROOT/desktop/build"
for f in main.js preload.js package.json package-lock.json; do
  [[ -f "$HERE/desktop/$f" ]] && cp "$HERE/desktop/$f" "$ROOT/desktop/"
done
[[ -f "$HERE/desktop/build/.gitkeep" ]] && cp "$HERE/desktop/build/.gitkeep" "$ROOT/desktop/build/" || true
[[ -f "$HERE/desktop/.gitignore" ]] && cp "$HERE/desktop/.gitignore" "$ROOT/desktop/"

# Empty data skeleton (models/projects created at runtime)
mkdir -p "$ROOT/data/projects" "$ROOT/data/models"
echo "# Turnwise stores projects and downloaded models here." > "$ROOT/data/README.txt"

echo "[3/3] Creating zip…"
mkdir -p "$OUT_DIR"
( cd "$STAGING" && zip -r -q "$OUT_DIR/$ZIP_NAME" turnwise )

rm -rf "$STAGING"
SIZE="$(du -h "$OUT_DIR/$ZIP_NAME" | cut -f1)"
echo ""
echo "Done: $OUT_DIR/$ZIP_NAME ($SIZE)"
echo "Send this zip to your friend. They should read INSTALL.md inside."

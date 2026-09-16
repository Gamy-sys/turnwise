#!/bin/bash
# Install Turnwise on a Mac — creates a clickable Turnwise.app icon.
# No Electron required. Double-click this file once.
set +e
set -u

cd "$(dirname "$0")"
ROOT="$(pwd)"
LOG="$ROOT/BUILD-LOG.txt"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

exec > >(tee "$LOG") 2>&1

pause() {
  echo
  echo "Press Enter to close this window."
  read -r _ || true
}

clear 2>/dev/null || true
echo "============================================"
echo "  Turnwise 0.3.0"
echo "  Mac installer (clickable app icon)"
echo "============================================"
echo
echo "Folder: $ROOT"
echo "Log:    $LOG"
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS only."
  pause
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: Homebrew is required."
  echo "Install from https://brew.sh then run this again."
  echo
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  pause
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installing Xcode Command Line Tools (dialog may appear)…"
  xcode-select --install || true
  echo "When CLT finishes, double-click this installer again."
  pause
  exit 1
fi

MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python@3.12")
command -v node >/dev/null 2>&1 || MISSING+=("node")
command -v npm >/dev/null 2>&1 || MISSING+=("node")
command -v ffmpeg >/dev/null 2>&1 || MISSING+=("ffmpeg")
if [[ ${#MISSING[@]} -gt 0 ]]; then
  # shellcheck disable=SC2207
  MISSING=($(printf '%s\n' "${MISSING[@]}" | awk '!a[$0]++'))
  echo "Installing: ${MISSING[*]}"
  brew install "${MISSING[@]}" || {
    echo "brew install failed"
    pause
    exit 1
  }
fi

# Seed bundled secrets (HF token for diarization) without overwriting existing keys
mkdir -p "$ROOT/data"
if [[ -f "$ROOT/packaging/friend-secrets.json" ]]; then
  if [[ ! -f "$ROOT/data/secrets.json" ]]; then
    cp "$ROOT/packaging/friend-secrets.json" "$ROOT/data/secrets.json"
    chmod 600 "$ROOT/data/secrets.json" 2>/dev/null || true
    echo "[secrets] installed bundled Hugging Face token for diarization"
  else
    echo "[secrets] keeping existing data/secrets.json"
  fi
fi

# Default settings: diarization ON, 2 speakers
python3 - <<'PY' || true
import json
from pathlib import Path
p = Path("data/global_settings.json")
cfg = {}
if p.exists():
    try: cfg = json.loads(p.read_text())
    except Exception: cfg = {}
cfg["enable_diarization"] = True
cfg.setdefault("num_speakers", 2)
cfg.setdefault("whisper_model", "medium")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2))
print("[settings] diarization=ON, num_speakers=2")
PY

echo
echo "[1/3] First-time Python setup (can take several minutes)…"
chmod +x "$ROOT/run.sh" "$ROOT/scripts/"*.sh 2>/dev/null || true
# Pre-create venv + install core + diarization so first click is faster
if [[ ! -d "$ROOT/backend/.venv" ]]; then
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install --upgrade pip wheel
fi
"$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
# CPU torch + pyannote for speaker labels
"$ROOT/backend/.venv/bin/pip" install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
  || "$ROOT/backend/.venv/bin/pip" install torch torchaudio
"$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements-diarization.txt" || {
  echo "WARNING: diarization packages failed to install — will retry on first run"
}

echo
echo "[2/3] Building UI (if needed)…"
if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  ( cd "$ROOT/frontend" && npm install && npm run build ) || {
    echo "frontend build failed"
    pause
    exit 1
  }
fi

echo
echo "[3/3] Creating clickable Turnwise.app…"
"$ROOT/scripts/create-mac-app.sh" "$HOME/Applications"
RC=$?

# Prefer wherever create-mac-app actually put it (/Applications or ~/Applications)
APP_PATH=""
if [[ -f "$HOME/Library/Application Support/Turnwise/app_path.txt" ]]; then
  APP_PATH="$(tr -d '\r\n' < "$HOME/Library/Application Support/Turnwise/app_path.txt")"
fi
for cand in "$APP_PATH" "/Applications/Turnwise.app" "$HOME/Applications/Turnwise.app" "$ROOT/Turnwise.app" "$HOME/Desktop/Turnwise.app"; do
  if [[ -n "$cand" && -d "$cand" ]]; then
    APP_PATH="$cand"
    break
  fi
done

if [[ $RC -ne 0 || -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "FAILED to create Turnwise.app — see $LOG"
  open -R "$LOG" 2>/dev/null || true
  pause
  exit 1
fi

echo
echo "============================================"
echo "  SUCCESS"
echo "============================================"
echo
echo "Turnwise icon is here:"
echo "  $APP_PATH"
if [[ -d "$HOME/Desktop/Turnwise.app" ]]; then
  echo "  $HOME/Desktop/Turnwise.app  (Desktop copy)"
fi
echo "  $ROOT/Turnwise.app  (inside the install folder)"
echo
echo "IMPORTANT: Finder sidebar \"Applications\" is /Applications."
echo "If you do not see it there, look on the Desktop or run:"
echo "  open \"$APP_PATH\""
echo
echo "If macOS blocks it: Right-click → Open → Open"
echo
# Reveal the exact icon in Finder and try to launch
open -R "$APP_PATH" 2>/dev/null || open "$(dirname "$APP_PATH")" 2>/dev/null || true
open "$APP_PATH" || true
echo
echo "Diarization is ON by default (Hugging Face token bundled)."
echo "Log: $LOG"
pause
exit 0

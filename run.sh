#!/usr/bin/env bash
# Turnwise - one-command launcher.
# - Creates/uses a Python venv, installs core + diarization deps if missing
# - Seeds bundled HF token for speaker labels
# - Builds the frontend if it hasn't been built
# - Starts the FastAPI server (which serves the built UI)
#
# Usage:
#   ./run.sh              # build frontend (if needed) + run server on :8000
#   ./run.sh --port 8010  # custom port
#   ./run.sh --dev        # run backend + Vite dev server (hot reload) together
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$HERE/backend"
FRONTEND="$HERE/frontend"
PORT=8000
DEV=0

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --dev) DEV=1; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

# --- ffmpeg check ---
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg is required."
  echo "  Mac:   brew install ffmpeg"
  echo "  Linux: sudo apt install ffmpeg"
  exit 1
fi

# --- pick a free port (auto-bump if the requested one is taken) ---
# Avoid GNU `timeout` (missing on many Macs). Use bash /dev/tcp only.
port_busy() {
  (exec 3<>/dev/tcp/127.0.0.1/"$1") >/dev/null 2>&1
}
REQ_PORT="$PORT"
for i in $(seq 0 20); do
  CAND=$((REQ_PORT + i))
  if ! port_busy "$CAND"; then PORT="$CAND"; break; fi
done
if [[ "$PORT" != "$REQ_PORT" ]]; then
  echo "[port] $REQ_PORT is in use — using $PORT instead"
fi

# --- Seed bundled secrets (friend Mac installer) ---
mkdir -p "$HERE/data"
if [[ -f "$HERE/packaging/friend-secrets.json" && ! -f "$HERE/data/secrets.json" ]]; then
  cp "$HERE/packaging/friend-secrets.json" "$HERE/data/secrets.json"
  chmod 600 "$HERE/data/secrets.json" 2>/dev/null || true
  echo "[secrets] bundled Hugging Face token installed for diarization"
fi

# --- Default global settings: diarization ON ---
if [[ ! -f "$HERE/data/global_settings.json" ]]; then
  cat > "$HERE/data/global_settings.json" <<'JSON'
{
  "enable_diarization": true,
  "num_speakers": 4,
  "whisper_model": "medium",
  "per_speaker_asr": true,
  "hybrid_mix_asr": true
}
JSON
  echo "[settings] diarization ON, 4 speakers"
fi

# --- Python venv + deps ---
if [[ ! -d "$BACKEND/.venv" ]]; then
  echo "[setup] creating Python venv…"
  python3 -m venv "$BACKEND/.venv"
  "$BACKEND/.venv/bin/pip" install --upgrade pip wheel >/dev/null
fi
if ! "$BACKEND/.venv/bin/python" -c "import faster_whisper, parselmouth, fastapi, docx, pykakasi, sudachipy, openai" >/dev/null 2>&1; then
  echo "[setup] installing backend dependencies…"
  "$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements.txt"
fi

# Diarization (pyannote + torch) — light check (find_spec) so we don't load torch every launch
if ! "$BACKEND/.venv/bin/python" -c "import importlib.util as u; import sys; sys.exit(0 if u.find_spec('pyannote.audio') and u.find_spec('torch') else 1)"; then
  echo "[setup] installing speaker diarization (torch + pyannote) — first time can take several minutes…"
  "$BACKEND/.venv/bin/pip" install torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
    || "$BACKEND/.venv/bin/pip" install torch torchaudio
  "$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements-diarization.txt" \
    || echo "[warn] diarization install incomplete — speaker labels may be unavailable"
fi

# Lip active-speaker (optional; video with visible faces)
if ! "$BACKEND/.venv/bin/python" -c "import importlib.util as u; import sys; sys.exit(0 if u.find_spec('cv2') and u.find_spec('mediapipe') else 1)"; then
  if [[ -f "$BACKEND/requirements-vision.txt" ]]; then
    echo "[setup] installing vision deps for lip active-speaker…"
    "$BACKEND/.venv/bin/pip" install -r "$BACKEND/requirements-vision.txt" \
      || echo "[warn] vision install incomplete — lip active-speaker disabled"
  fi
fi

# Write the chosen port so the Mac .app can find us without guessing
echo "$PORT" > "$HERE/data/last_port.txt"

# --- Frontend build ---
if [[ $DEV -eq 0 ]]; then
  if [[ ! -f "$FRONTEND/dist/index.html" ]]; then
    echo "[setup] building frontend…"
    ( cd "$FRONTEND" && npm install && npm run build )
  fi
  echo "[run] Turnwise on http://127.0.0.1:$PORT"
  echo "[run] (first start can take 1–3 minutes while Python loads)"
  exec "$BACKEND/.venv/bin/python" -m uvicorn app.main:app \
    --app-dir "$BACKEND" --host 127.0.0.1 --port "$PORT"
else
  echo "[dev] backend on :$PORT, Vite dev server on :5173 (open http://localhost:5173)"
  "$BACKEND/.venv/bin/python" -m uvicorn app.main:app \
    --app-dir "$BACKEND" --host 127.0.0.1 --port "$PORT" --reload &
  BACK_PID=$!
  trap "kill $BACK_PID 2>/dev/null || true" EXIT
  ( cd "$FRONTEND" && CA_BACKEND_PORT="$PORT" npm install && CA_BACKEND_PORT="$PORT" npm run dev )
fi

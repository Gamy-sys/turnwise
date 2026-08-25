#!/usr/bin/env bash
# Turnwise - one-command launcher.
# - Creates/uses a Python venv, installs core deps if missing
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --dev) DEV=1; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

# --- ffmpeg check ---
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg is required. Install it, e.g.:  sudo apt install ffmpeg"
  exit 1
fi

# --- pick a free port (auto-bump if the requested one is taken) ---
port_busy() { timeout 0.4 bash -c "exec 3<>/dev/tcp/127.0.0.1/$1" 2>/dev/null; }
REQ_PORT="$PORT"
for i in $(seq 0 20); do
  CAND=$((REQ_PORT + i))
  if ! port_busy "$CAND"; then PORT="$CAND"; break; fi
done
if [[ "$PORT" != "$REQ_PORT" ]]; then
  echo "[port] $REQ_PORT is in use — using $PORT instead"
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

# --- Frontend build ---
if [[ $DEV -eq 0 ]]; then
  if [[ ! -f "$FRONTEND/dist/index.html" ]]; then
    echo "[setup] building frontend…"
    ( cd "$FRONTEND" && npm install && npm run build )
  fi
  echo "[run] Turnwise on http://127.0.0.1:$PORT"
  exec "$BACKEND/.venv/bin/python" -m uvicorn app.main:app \
    --app-dir "$BACKEND" --host 127.0.0.1 --port "$PORT"
else
  echo "[dev] backend on :$PORT, Vite dev server on :5173 (open http://localhost:5173)"
  "$BACKEND/.venv/bin/python" -m uvicorn app.main:app \
    --app-dir "$BACKEND" --host 127.0.0.1 --port "$PORT" --reload &
  BACK_PID=$!
  trap "kill $BACK_PID 2>/dev/null || true" EXIT
  # Point the Vite dev proxy at the backend port we actually bound to.
  ( cd "$FRONTEND" && CA_BACKEND_PORT="$PORT" npm install && CA_BACKEND_PORT="$PORT" npm run dev )
fi

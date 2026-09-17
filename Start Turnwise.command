#!/bin/bash
# Backup Mac launcher — double-click if the Turnwise.app icon fails.
# Opens a Terminal window so you can see startup progress.
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
chmod +x ./run.sh 2>/dev/null || true
echo "Starting Turnwise…"
echo "When you see:  Turnwise on http://127.0.0.1:8000"
echo "open that address in your browser (or wait — we open it for you)."
echo

# Start server in background of this Terminal
./run.sh &
PID=$!

URL=""
for i in $(seq 1 900); do
  if [[ -f data/last_port.txt ]]; then
    port="$(tr -d '\r\n' < data/last_port.txt)"
    if curl -fsS "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      URL="http://127.0.0.1:${port}/"
      break
    fi
  fi
  for port in 8000 8001 8002 8003 8004 8005; do
    if curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1; then
      URL="http://127.0.0.1:$port/"
      break 2
    fi
  done
  # print a heartbeat every 15s
  if (( i % 15 == 0 )); then
    echo "… still starting ($i seconds). First launch can be slow."
  fi
  sleep 1
done

if [[ -n "$URL" ]]; then
  echo "Ready: $URL"
  open "$URL"
else
  echo "Timed out waiting for the UI."
  echo "Check this Terminal for errors."
fi

wait "$PID" 2>/dev/null || true

#!/usr/bin/env bash
# Start Turnwise (if needed) and open it in the default browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HERE/.turnwise-server.log"
PIDFILE="$HERE/.turnwise-server.pid"
PORT_FILE="$HERE/.turnwise.port"

# Back-compat with older CA Studio launch files
if [[ ! -f "$PIDFILE" && -f "$HERE/.ca-studio-server.pid" ]]; then
  PIDFILE="$HERE/.ca-studio-server.pid"
  LOG="$HERE/.ca-studio-server.log"
  PORT_FILE="$HERE/.ca-studio.port"
fi

notify() {
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "Turnwise" "$1"
  fi
}

port_busy() {
  # Avoid GNU `timeout` (missing on many Macs).
  (exec 3<>/dev/tcp/127.0.0.1/"$1") >/dev/null 2>&1
}

http_ok() {
  curl -sf --max-time 1 "http://127.0.0.1:$1/" >/dev/null 2>&1
}

find_running_port() {
  local p
  for p in $(seq 8000 8020); do
    if port_busy "$p" && http_ok "$p"; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

start_server() {
  if [[ -f "$PIDFILE" ]]; then
    local old_pid
    old_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      return 0
    fi
  fi

  : >"$LOG"
  nohup "$HERE/run.sh" >>"$LOG" 2>&1 &
  echo "$!" >"$PIDFILE"

  local i
  for i in $(seq 1 120); do
    sleep 0.5
    if p="$(find_running_port)"; then
      echo "$p" >"$PORT_FILE"
      return 0
    fi
  done

  notify "Failed to start. See $LOG"
  exit 1
}

main() {
  local port
  if ! port="$(find_running_port)"; then
    start_server
    port="$(find_running_port)" || {
      notify "Server did not respond. See $LOG"
      exit 1
    }
  fi

  echo "$port" >"$PORT_FILE"
  xdg-open "http://127.0.0.1:${port}/" >/dev/null 2>&1 || \
    open "http://127.0.0.1:${port}/" >/dev/null 2>&1 || \
    sensible-browser "http://127.0.0.1:${port}/" >/dev/null 2>&1 || \
    notify "Open http://127.0.0.1:${port}/ in your browser"
}

main "$@"

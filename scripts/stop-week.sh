#!/usr/bin/env bash
# Stop what scripts/start-week.sh started: website, backend, the Tailscale
# HTTPS addresses, and keep-awake. Qdrant and the Tailscale connection are
# left running; they are harmless and Qdrant restarts on its own anyway.
#
# Usage, from the repo root:  ./scripts/stop-week.sh

set -u
cd "$(dirname "$0")/.."

stop_port() {  # stop_port <port> <label>
  local pids
  pids=$(lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null)
  if [ -z "$pids" ]; then
    echo "  $2: not running"
    return
  fi
  kill $pids 2>/dev/null
  for _ in $(seq 1 10); do
    lsof -nP -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
  if lsof -nP -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  $2: still running after 10s (pids: $pids)"
  else
    echo "  $2: stopped"
  fi
}

stop_port 3000 "website (3000)"
stop_port 8000 "backend (8000)"

tailscale serve --https=443 off >/dev/null 2>&1
tailscale serve --https=8443 off >/dev/null 2>&1
echo "  Tailscale HTTPS addresses: off"

if pkill -f "caffeinate -dims" 2>/dev/null; then
  echo "  keep-awake: off"
else
  echo "  keep-awake: was not on"
fi

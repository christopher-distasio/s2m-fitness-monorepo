#!/usr/bin/env bash
# Start everything the phone needs to log meals against this Mac:
#   Qdrant (food database) -> backend (8000) -> website (3000)
#   -> Tailscale HTTPS addresses -> keep the Mac awake -> health checks.
#
# Safe to run again: anything already running is left alone.
# Stop it all with scripts/stop-week.sh.
#
# Usage, from the repo root:  ./scripts/start-week.sh

set -u
cd "$(dirname "$0")/.."
REPO="$(pwd)"
mkdir -p logs

ok()   { printf "  \033[32mOK\033[0m   %s\n" "$1"; }
warn() { printf "  \033[33mWARN\033[0m %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; }
port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for() {  # wait_for <url> <seconds>
  local url="$1" tries="$2"
  for _ in $(seq 1 "$tries"); do
    curl -s -m 5 -o /dev/null "$url" && return 0
    sleep 1
  done
  return 1
}

echo "1. Food database (Qdrant)"
if ! docker info >/dev/null 2>&1; then
  echo "     Docker is not running; opening Docker Desktop..."
  open -a Docker
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
if ! docker info >/dev/null 2>&1; then
  fail "Docker did not start. Open Docker Desktop, then run this again."
  exit 1
fi
docker start qdrant >/dev/null 2>&1
if wait_for http://127.0.0.1:6333/collections/food-vectors 60; then
  points=$(curl -s http://127.0.0.1:6333/collections/food-vectors \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])")
  if [ "$points" = "2013088" ]; then
    ok "Qdrant up, food-vectors has $points points"
  else
    warn "Qdrant up, but food-vectors has $points points (expected 2013088)"
  fi
else
  fail "Qdrant did not answer on port 6333"
  exit 1
fi

echo "2. Backend (port 8000)"
if port_in_use 8000; then
  ok "already running (left as is)"
else
  PYTHONUNBUFFERED=1 nohup poetry run uvicorn backend.main:app \
    --host 127.0.0.1 --port 8000 >> logs/backend-dev.log 2>&1 &
  if wait_for http://127.0.0.1:8000/test 60; then
    ok "started, logging to logs/backend-dev.log"
  else
    fail "backend did not start; see the end of logs/backend-dev.log"
    exit 1
  fi
fi

echo "3. Website (port 3000, this Mac and Tailscale only)"
if port_in_use 3000; then
  ok "already running (left as is)"
else
  nohup npm --prefix frontend run dev -- -H 127.0.0.1 -p 3000 \
    >> logs/frontend-dev.log 2>&1 &
  if wait_for http://127.0.0.1:3000/login 90; then
    ok "started, logging to logs/frontend-dev.log"
  else
    fail "website did not start; see the end of logs/frontend-dev.log"
    exit 1
  fi
fi

echo "4. Tailscale"
if ! tailscale status >/dev/null 2>&1; then
  tailscale up >/dev/null 2>&1
fi
HOST=$(tailscale status --json 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null)
if [ -z "$HOST" ]; then
  fail "Tailscale is not connected. Open the Tailscale app and sign in."
  exit 1
fi
tailscale serve --bg --https=443 http://127.0.0.1:3000 >/dev/null 2>&1
tailscale serve --bg --https=8443 http://127.0.0.1:8000 >/dev/null 2>&1
ok "connected as $HOST"

echo "5. Keep this Mac awake"
if pgrep -f "caffeinate -dims" >/dev/null; then
  ok "already on"
else
  nohup caffeinate -dims >/dev/null 2>&1 &
  ok "on (stays on until scripts/stop-week.sh)"
fi
if pmset -g batt | grep -q "Battery Power"; then
  warn "running on battery. Plug the Mac in, and keep the lid open."
fi

echo "6. Checks"
if curl -s -m 20 -o /dev/null -w "%{http_code}" "https://$HOST:8443/test" | grep -q 200; then
  ok "backend reachable at https://$HOST:8443"
else
  fail "backend not reachable through Tailscale"
fi
if curl -s -m 30 -o /dev/null -w "%{http_code}" "https://$HOST/login" | grep -q 200; then
  ok "website reachable at https://$HOST"
else
  fail "website not reachable through Tailscale"
fi
SUPA_URL=$(grep '^NEXT_PUBLIC_SUPABASE_URL=' frontend/.env.local 2>/dev/null | cut -d= -f2- | tr -d '"')
SUPA_KEY=$(grep '^NEXT_PUBLIC_SUPABASE_ANON_KEY=' frontend/.env.local 2>/dev/null | cut -d= -f2- | tr -d '"')
if [ -n "$SUPA_URL" ] && curl -s -m 20 -o /dev/null -w "%{http_code}" \
    "$SUPA_URL/auth/v1/health" -H "apikey: $SUPA_KEY" | grep -q 200; then
  ok "login service (Supabase) is up"
else
  fail "login service (Supabase) is not answering. If the project is paused, restore it at supabase.com/dashboard."
fi

echo
echo "On your phone (Tailscale on), open:  https://$HOST"

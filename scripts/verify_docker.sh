#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERIFY_PROJECT="ibkr_show_verify"

FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
ES_PORT="${ES_PORT:-9200}"
REDIS_PORT="${REDIS_PORT:-6379}"

HEALTH_URL="http://localhost:${FRONTEND_PORT}/health"
BOOTSTRAP_URL="http://localhost:${FRONTEND_PORT}/api/auth/bootstrap/init"
BOOTSTRAP_STATUS_URL="http://localhost:${FRONTEND_PORT}/api/auth/bootstrap/status"
LOGIN_URL="http://localhost:${FRONTEND_PORT}/api/auth/login"
SESSION_URL="http://localhost:${FRONTEND_PORT}/api/auth/session"
SYSTEM_STATUS_URL="http://localhost:${FRONTEND_PORT}/api/admin/system/status"
ES_URL="http://localhost:${ES_PORT}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}/"

COOKIE_JAR="$(mktemp)"
ENV_BACKUP=""
ORIGINAL_ENV_EXISTS=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { printf '\n\033[1;36m>>> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mFAIL: %s\033[0m\n' "$*"; dump_logs; exit 1; }

compose() {
  COMPOSE_PROJECT_NAME="$VERIFY_PROJECT" docker compose "$@"
}

dump_logs() {
  echo ""
  echo "=== compose ps ==="
  compose ps 2>/dev/null || true
  for svc in worker-init backend frontend; do
    echo ""
    echo "=== compose logs $svc --tail=100 ==="
    compose logs "$svc" --tail=100 2>/dev/null || true
  done
}

cleanup_compose() {
  COMPOSE_PROJECT_NAME="$VERIFY_PROJECT" docker compose down -v --remove-orphans 2>/dev/null || true
}

cleanup_env() {
  if [ "$ORIGINAL_ENV_EXISTS" -eq 1 ]; then
    if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
      cp "$ENV_BACKUP" .env
      rm -f "$ENV_BACKUP"
      echo "  Restored original .env"
    fi
  else
    rm -f .env
    echo "  Removed temporary .env"
  fi
}

wait_for_health() {
  local max_wait=120
  local elapsed=0
  log "Waiting for $HEALTH_URL (max ${max_wait}s)..."
  while [ "$elapsed" -lt "$max_wait" ]; do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
      echo "  Health check passed after ${elapsed}s."
      return 0
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done
  fail "Health check did not respond within ${max_wait}s"
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"

# ---------------------------------------------------------------------------
# Prepare .env
# ---------------------------------------------------------------------------

if [ -f .env ]; then
  ORIGINAL_ENV_EXISTS=1
  ENV_BACKUP="$(mktemp)"
  cp .env "$ENV_BACKUP"
  echo "  Backed up existing .env"
fi

if [ "${CLEANUP:-0}" = "1" ]; then
  trap 'cleanup_compose; cleanup_env; rm -f "$COOKIE_JAR"' EXIT
else
  trap 'cleanup_env; rm -f "$COOKIE_JAR"' EXIT
fi

cat > .env <<EOF
COMPOSE_PROJECT_NAME=${VERIFY_PROJECT}
FRONTEND_PORT=${FRONTEND_PORT}
BACKEND_PORT=${BACKEND_PORT}
ES_PORT=${ES_PORT}
REDIS_PORT=${REDIS_PORT}
ES_JAVA_OPTS=-Xms512m -Xmx512m
APP_ENV=docker
AUTH_USERNAME=admin
AUTH_PASSWORD=change-me
AUTH_SESSION_SECRET=verify-session-secret
DAILY_REVIEW_INTERNAL_TOKEN=verify-internal-token
DEMO_MODE=true
EOF
echo "  Wrote verification .env"

# ---------------------------------------------------------------------------
# Docker Compose lifecycle
# ---------------------------------------------------------------------------

log "docker compose config"
compose config --quiet || fail "docker compose config failed"

log "docker compose build"
compose build --no-cache || fail "docker compose build failed"

log "docker compose down (clean slate)"
compose down -v --remove-orphans 2>/dev/null || true

log "docker compose up -d"
compose up -d || fail "docker compose up failed"

# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------

wait_for_health

# ---------------------------------------------------------------------------
# 2. Demo data
# ---------------------------------------------------------------------------

log "Checking demo data in Elasticsearch..."
INDICES=(
  "ibkr_account_daily_snapshot_v1"
  "ibkr_position_daily_snapshot_v1"
  "ibkr_trade_records_v1"
  "ibkr_cash_flow_records_v1"
)
for index in "${INDICES[@]}"; do
  count="$(curl -sf "${ES_URL}/${index}/_count" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))")"
  echo "  ${index}: ${count}"
  if [ "$count" -le 0 ] 2>/dev/null; then
    fail "Demo index ${index} has 0 documents"
  fi
done
echo "  All demo indices have data."

# ---------------------------------------------------------------------------
# 3. Bootstrap init
# ---------------------------------------------------------------------------

log "Initializing admin account via bootstrap API..."
http_code="$(curl -sf -o /dev/null -w '%{http_code}' \
  -X POST "$BOOTSTRAP_URL" \
  -H 'Content-Type: application/json' \
  -d '{"username":"verify-admin","password":"verify-password-123"}')"
echo "  POST /api/auth/bootstrap/init -> ${http_code}"
[ "$http_code" = "200" ] || fail "Bootstrap init returned ${http_code}"

log "Checking bootstrap status..."
bootstrap_json="$(curl -sf "$BOOTSTRAP_STATUS_URL")"
initialized="$(echo "$bootstrap_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('initialized', False))")"
echo "  initialized=${initialized}"
[ "$initialized" = "True" ] || fail "Bootstrap status not initialized"

# ---------------------------------------------------------------------------
# 4. Login
# ---------------------------------------------------------------------------

log "Logging in..."
http_code="$(curl -sf -o /dev/null -w '%{http_code}' \
  -c "$COOKIE_JAR" \
  -X POST "$LOGIN_URL" \
  -H 'Content-Type: application/json' \
  -d '{"username":"verify-admin","password":"verify-password-123"}')"
echo "  POST /api/auth/login -> ${http_code}"
[ "$http_code" = "200" ] || fail "Login returned ${http_code}"

log "Checking session..."
session_json="$(curl -sf -b "$COOKIE_JAR" "$SESSION_URL")"
authenticated="$(echo "$session_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('authenticated', False))")"
echo "  authenticated=${authenticated}"
[ "$authenticated" = "True" ] || fail "Session not authenticated"

# ---------------------------------------------------------------------------
# 5. System status API
# ---------------------------------------------------------------------------

log "Checking /api/admin/system/status..."
status_json="$(curl -sf -b "$COOKIE_JAR" "$SYSTEM_STATUS_URL")"
echo "$status_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
components = [c['name'] for c in data.get('components', [])]
required = ['backend','bootstrap','elasticsearch','redis','ibkr','longbridge','llm','email','demo_data','worker']
missing = [r for r in required if r not in components]
if missing:
    print(f'  Missing components: {missing}')
    sys.exit(1)
print(f'  overall_status={data[\"overall_status\"]}')
print(f'  components={len(components)}')
print('  All required components present.')
" || fail "System status check failed"

# ---------------------------------------------------------------------------
# 6. Frontend HTML
# ---------------------------------------------------------------------------

log "Checking frontend HTML..."
frontend_html="$(curl -sf "$FRONTEND_URL")"
if echo "$frontend_html" | grep -q 'id="app"\|<script.*assets'; then
  echo "  Frontend HTML contains app entry point."
else
  fail "Frontend HTML does not contain expected app entry"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

log "All verification checks passed!"
if [ "${CLEANUP:-0}" = "1" ]; then
  echo "  CLEANUP=1 set, containers will be torn down on exit."
fi

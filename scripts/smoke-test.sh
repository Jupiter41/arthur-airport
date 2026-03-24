#!/usr/bin/env bash
# smoke-test.sh — Full-stack smoke test for Arthur International Airport
# Usage: ./scripts/smoke-test.sh
# Prerequisites: docker, docker compose, curl, jq

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
GATEWAY="http://localhost:3000"
DASHBOARD="http://localhost:5173"

log()   { echo -e "${GREEN}[PASS]${NC} $1"; ((PASS++)); }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; ((FAIL++)); }

check_http() {
    local url="$1"
    local label="$2"
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "000")
    if [[ "$code" =~ ^2 ]]; then
        log "$label → HTTP $code"
    else
        fail "$label → HTTP $code"
    fi
}

# ─── 1. Start the stack ─────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Arthur International Airport — Smoke Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if [[ "${SKIP_BUILD:-}" != "1" ]]; then
    echo "Building and starting the full stack..."
    docker compose up --build -d
else
    echo "SKIP_BUILD=1 — assuming stack is already running."
fi

# ─── 2. Wait for services ───────────────────────────────────────
echo ""
echo "Waiting for services to become healthy (up to 120s)..."

SERVICES=(
    "http://localhost:8001/health flight-service"
    "http://localhost:8002/health passenger-service"
    "http://localhost:8003/health baggage-service"
    "http://localhost:8004/health weather-service"
    "http://localhost:8005/health incident-service"
    "http://localhost:8006/health sim-orchestrator"
    "$GATEWAY/health api-gateway"
)

MAX_WAIT=120
for entry in "${SERVICES[@]}"; do
    url=$(echo "$entry" | awk '{print $1}')
    name=$(echo "$entry" | awk '{print $2}')
    elapsed=0
    while true; do
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || echo "000")
        if [[ "$code" =~ ^2 ]]; then
            log "$name is healthy"
            break
        fi
        if [[ $elapsed -ge $MAX_WAIT ]]; then
            fail "$name did not become healthy within ${MAX_WAIT}s"
            break
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
done

# ─── 3. Dashboard reachable ─────────────────────────────────────
echo ""
echo "Checking dashboard..."
check_http "$DASHBOARD" "React dashboard"

# ─── 4. Readiness endpoints ─────────────────────────────────────
echo ""
echo "Checking /ready endpoints..."
for port in 8001 8002 8003 8004 8005 8006; do
    check_http "http://localhost:$port/ready" "Service on port $port /ready"
done

# ─── 5. Authenticate ────────────────────────────────────────────
echo ""
echo "Authenticating with gateway..."
TOKEN=$(curl -s -X POST "$GATEWAY/auth/token" \
    -H 'Content-Type: application/json' \
    -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r '.token // empty')

if [[ -n "$TOKEN" ]]; then
    log "Got JWT token"
else
    fail "Could not obtain JWT token"
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
    echo "═══════════════════════════════════════════════════════════════"
    exit 1
fi

AUTH="-H \"Authorization: Bearer $TOKEN\""

# ─── 6. Gateway proxy routes ────────────────────────────────────
echo ""
echo "Checking gateway proxy routes..."
ROUTES=(
    "/api/v1/flights flights"
    "/api/v1/passengers passengers"
    "/api/v1/baggage baggage"
    "/api/v1/weather weather"
    "/api/v1/incidents incidents"
)

for entry in "${ROUTES[@]}"; do
    route=$(echo "$entry" | awk '{print $1}')
    name=$(echo "$entry" | awk '{print $2}')
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
        -H "Authorization: Bearer $TOKEN" "$GATEWAY$route" 2>/dev/null || echo "000")
    if [[ "$code" =~ ^2 ]]; then
        log "GET $route → HTTP $code"
    else
        fail "GET $route → HTTP $code"
    fi
done

# ─── 7. Inject incidents ────────────────────────────────────────
echo ""
echo "Injecting test incidents..."
INCIDENT_TYPES=("runway_incursion" "security_breach" "baggage_fire" "system_failure")
SEVERITIES=("critical" "high" "high" "medium")
LOCATIONS=("runway-09L" "terminal-A-zone-2" "baggage-hall-B" "conveyor-sorting")

for i in "${!INCIDENT_TYPES[@]}"; do
    type="${INCIDENT_TYPES[$i]}"
    sev="${SEVERITIES[$i]}"
    loc="${LOCATIONS[$i]}"

    resp=$(curl -s -X POST "$GATEWAY/api/v1/incidents/inject" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"$type\",\"severity\":\"$sev\",\"location\":\"$loc\"}" 2>/dev/null)

    id=$(echo "$resp" | jq -r '.id // .incident_id // empty' 2>/dev/null)
    if [[ -n "$id" ]]; then
        log "Injected $type ($sev) → id=$id"
    else
        fail "Failed to inject $type"
    fi
done

# ─── 8. Wait and verify cascades ────────────────────────────────
echo ""
echo "Waiting 15s for cascades to propagate..."
sleep 15

inc_count=$(curl -s -H "Authorization: Bearer $TOKEN" "$GATEWAY/api/v1/incidents" 2>/dev/null \
    | jq 'if type == "array" then length else .total // .count // 0 end' 2>/dev/null || echo "0")

if [[ "$inc_count" -gt 4 ]]; then
    log "Cascades produced child incidents (total: $inc_count)"
else
    warn "Expected cascades but only found $inc_count incidents"
fi

# ─── 9. Neo4j has data ──────────────────────────────────────────
echo ""
echo "Checking Neo4j for seeded flights..."
flight_count=$(curl -s -H "Authorization: Bearer $TOKEN" "$GATEWAY/api/v1/flights" 2>/dev/null \
    | jq 'if type == "array" then length else .total // .count // 0 end' 2>/dev/null || echo "0")

if [[ "$flight_count" -gt 0 ]]; then
    log "Neo4j has $flight_count flights"
else
    fail "No flights found — seeding may have failed"
fi

# ─── 10. Summary ────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo "═══════════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0

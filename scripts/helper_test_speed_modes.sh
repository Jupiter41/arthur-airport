#!/usr/bin/env bash
# Helper script: Test simulation speed modes (REALTIME, FAST, BULK)
# Usage: ./scripts/helper_test_speed_modes.sh [60|600|3600]
#
# Tests that the simulation runs correctly at the given speed:
#   - Checks sim/status for mode field
#   - Verifies services are healthy
#   - Checks Neo4j for consistent state
#   - Monitors for queue explosions or errors

set -euo pipefail

BASE_URL="${SIM_URL:-http://localhost:3000}"
SPEED="${1:-60}"

echo "=== Testing speed mode at ${SPEED}× ==="

# Get token
TOKEN=$(curl -s -X POST "$BASE_URL/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to get auth token"
  exit 1
fi

AUTH="Authorization: Bearer $TOKEN"

# Check current status
echo -e "\n--- Current sim status ---"
curl -s "$BASE_URL/api/v1/sim/status" -H "$AUTH" | python3 -m json.tool

# Set speed
echo -e "\n--- Setting speed to ${SPEED}× ---"
curl -s -X PATCH "$BASE_URL/api/v1/sim/speed" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"speed_multiplier\": $SPEED}" | python3 -m json.tool

# Wait and sample status every 5 real seconds for 30 seconds
echo -e "\n--- Monitoring for 30 seconds (5s intervals) ---"
for i in $(seq 1 6); do
  sleep 5
  STATUS=$(curl -s "$BASE_URL/api/v1/sim/status" -H "$AUTH")
  SIM_TIME=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sim_time','?'))")
  MODE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode','?'))")
  TICK=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tick_number','?'))")
  echo "  [$i/6] sim_time=$SIM_TIME mode=$MODE tick=$TICK"
done

# Check service health
echo -e "\n--- Service health check ---"
for svc in flight-service passenger-service baggage-service weather-service incident-service sim-orchestrator; do
  PORT=$(case $svc in
    flight-service) echo 8001;;
    passenger-service) echo 8002;;
    baggage-service) echo 8003;;
    weather-service) echo 8004;;
    incident-service) echo 8005;;
    sim-orchestrator) echo 8006;;
  esac)
  HEALTH=$(curl -s "http://localhost:$PORT/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "FAIL")
  echo "  $svc: $HEALTH"
done

# Check Neo4j for consistent state
echo -e "\n--- Neo4j passenger state ---"
curl -s "http://localhost:8002/api/v1/passengers/stats" -H "$AUTH" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (stats endpoint not available)"

# Check for queue depth issues
echo -e "\n--- Security queue depths ---"
for terminal in A B C; do
  DEPTH=$(curl -s "http://localhost:9090/api/v1/query?query=security_queue_depth{terminal=\"$terminal\"}" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '?')" 2>/dev/null || echo "?")
  echo "  Terminal $terminal: $DEPTH"
done

# Reset to 60× at the end
echo -e "\n--- Resetting to 60× ---"
curl -s -X PATCH "$BASE_URL/api/v1/sim/speed" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"speed_multiplier": 60}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Speed: {d.get('speed_multiplier')}× Mode: {d.get('mode')}\")"

echo -e "\n=== Test complete ==="

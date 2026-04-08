#!/usr/bin/env bash
# Test all debug injection endpoints in sim-orchestrator
# Usage: ./scripts/helper_test_debug_endpoints.sh
# Requires: curl, python3, jq (optional)

set -euo pipefail

API="http://localhost:3000"
DIRECT="http://localhost:8006"

echo "=== Getting auth token ==="
TOKEN=$(curl -s -X POST "$API/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token acquired: ${TOKEN:0:20}..."

AUTH="Authorization: Bearer $TOKEN"

echo ""
echo "=== 1. Test flight injection ==="
FLIGHT_RESULT=$(curl -s -X POST "$API/api/v1/debug/inject/flight" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"direction":"departure","seed_passengers":true,"seed_baggage":true}')
echo "$FLIGHT_RESULT" | python3 -m json.tool 2>/dev/null || echo "$FLIGHT_RESULT"
FLIGHT_ID=$(echo "$FLIGHT_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('flight_id',''))" 2>/dev/null || echo "")
echo "Created flight_id: $FLIGHT_ID"

echo ""
echo "=== 2. Test passenger injection ==="
if [ -n "$FLIGHT_ID" ]; then
  PAX_RESULT=$(curl -s -X POST "$API/api/v1/debug/inject/passengers" \
    -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"flight_id\":\"$FLIGHT_ID\",\"count\":5,\"status\":\"at_gate\"}")
  echo "$PAX_RESULT" | python3 -m json.tool 2>/dev/null || echo "$PAX_RESULT"
else
  echo "SKIP — no flight_id from previous test"
fi

echo ""
echo "=== 3. Test baggage injection ==="
if [ -n "$FLIGHT_ID" ]; then
  BAG_RESULT=$(curl -s -X POST "$API/api/v1/debug/inject/baggage" \
    -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"flight_id\":\"$FLIGHT_ID\",\"count\":3,\"zone_status\":\"screening\"}")
  echo "$BAG_RESULT" | python3 -m json.tool 2>/dev/null || echo "$BAG_RESULT"
else
  echo "SKIP — no flight_id from previous test"
fi

echo ""
echo "=== 4. Test Cypher console ==="
CYPHER_RESULT=$(curl -s -X POST "$API/api/v1/debug/cypher" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"query":"MATCH (f:Flight) RETURN f.flight_number, f.status LIMIT 5"}')
echo "$CYPHER_RESULT" | python3 -m json.tool 2>/dev/null || echo "$CYPHER_RESULT"

echo ""
echo "=== 5. Test entity inspector ==="
if [ -n "$FLIGHT_ID" ]; then
  ENTITY_RESULT=$(curl -s "$API/api/v1/debug/entity/Flight/$FLIGHT_ID" \
    -H "$AUTH")
  echo "$ENTITY_RESULT" | python3 -m json.tool 2>/dev/null || echo "$ENTITY_RESULT"
else
  echo "SKIP — no flight_id"
fi

echo ""
echo "=== 6. Test snapshot list ==="
SNAP_RESULT=$(curl -s "$API/api/v1/debug/snapshots" -H "$AUTH")
echo "$SNAP_RESULT" | python3 -m json.tool 2>/dev/null || echo "$SNAP_RESULT"

echo ""
echo "=== 7. Test snapshot create ==="
SNAP_CREATE=$(curl -s -X POST "$API/api/v1/debug/snapshot" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"name":"debug-test"}')
echo "$SNAP_CREATE" | python3 -m json.tool 2>/dev/null || echo "$SNAP_CREATE"

echo ""
echo "=== 8. Test ADS-B states ==="
ADSB_RESULT=$(curl -s "$API/api/v1/flights/adsb-states" -H "$AUTH")
ADSB_COUNT=$(echo "$ADSB_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Aircraft: {d.get('metadata',{}).get('aircraft_count',0)}\")" 2>/dev/null || echo "Parse error")
echo "$ADSB_COUNT"
echo "$ADSB_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('metadata',{}), indent=2))" 2>/dev/null || echo "$ADSB_RESULT"

echo ""
echo "=== All debug endpoint tests complete ==="

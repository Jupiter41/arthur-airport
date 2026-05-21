#!/usr/bin/env bash
# helper_test_cost_endpoints.sh — Hit all cost-service REST endpoints and verify response shapes.
#
# Usage:
#   bash scripts/helper_test_cost_endpoints.sh [BASE_URL]
#
# Arguments:
#   BASE_URL  API base URL (default: http://localhost:3000/api/v1)
#
# Requirements:
#   - curl and jq installed
#   - The stack running (at minimum: cost-service, api-gateway, neo4j, kafka)
#
# Examples:
#   bash scripts/helper_test_cost_endpoints.sh                        # via gateway
#   bash scripts/helper_test_cost_endpoints.sh http://localhost:8008/api/v1  # direct to cost-service

set -euo pipefail

BASE="${1:-http://localhost:3000/api/v1}"

# Get auth token (gateway only, direct access doesn't need it)
TOKEN=""
if [[ "$BASE" == *":3000"* ]]; then
    TOKEN=$(curl -s -X POST "${BASE%%/api/v1}/auth/token" \
        -H 'Content-Type: application/json' \
        -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r '.token // empty')
fi

auth_header() {
    if [[ -n "$TOKEN" ]]; then
        echo "Authorization: Bearer $TOKEN"
    else
        echo "X-No-Auth: true"
    fi
}

echo "═══════════════════════════════════════════════════════"
echo "  Cost Service Endpoint Test — $BASE"
echo "═══════════════════════════════════════════════════════"
echo ""

# 1. Summary
echo "── GET /costs/summary ──"
curl -s -H "$(auth_header)" "$BASE/costs/summary" | jq .
echo ""

# 2. P&L for day 1
echo "── GET /costs/pnl?day=1 ──"
curl -s -H "$(auth_header)" "$BASE/costs/pnl?day=1" | jq .
echo ""

# 3. Hourly curve for day 1
echo "── GET /costs/hourly?day=1 ──"
curl -s -H "$(auth_header)" "$BASE/costs/hourly?day=1" | jq .
echo ""

# 4. Incident ranking for day 1
echo "── GET /costs/incidents/ranking?day=1&limit=5 ──"
curl -s -H "$(auth_header)" "$BASE/costs/incidents/ranking?day=1&limit=5" | jq .
echo ""

# 5. Recommendations
echo "── GET /costs/recommendations ──"
curl -s -H "$(auth_header)" "$BASE/costs/recommendations" | jq .
echo ""

# 6. Cost rates
echo "── GET /costs/rates ──"
curl -s -H "$(auth_header)" "$BASE/costs/rates" | jq 'keys'
echo ""

# 7. Shape validation
echo "═══════════════════════════════════════════════════════"
echo "  Response Shape Validation"
echo "═══════════════════════════════════════════════════════"
echo ""

# Validate summary shape
echo -n "Summary has required fields... "
SUMMARY=$(curl -s -H "$(auth_header)" "$BASE/costs/summary")
if echo "$SUMMARY" | jq -e '.total_cost_eur != null and .total_revenue_eur != null and .net_eur != null and .margin_pct != null and .by_category != null and .eu261_exposure_eur != null' > /dev/null 2>&1; then
    echo "✅ OK"
else
    echo "❌ FAIL — missing fields"
    echo "$SUMMARY" | jq 'keys'
fi

# Validate hourly shape
echo -n "Hourly wrapped in {hours: [...]}... "
HOURLY=$(curl -s -H "$(auth_header)" "$BASE/costs/hourly?day=1")
if echo "$HOURLY" | jq -e '.hours | type == "array"' > /dev/null 2>&1; then
    echo "✅ OK"
    COUNT=$(echo "$HOURLY" | jq '.hours | length')
    echo "  → $COUNT hourly data points"
    if [ "$COUNT" -gt 0 ]; then
        echo -n "  → First item has cost_eur, revenue_eur, net_eur... "
        if echo "$HOURLY" | jq -e '.hours[0] | .cost_eur != null and .revenue_eur != null and .net_eur != null' > /dev/null 2>&1; then
            echo "✅ OK"
        else
            echo "❌ FAIL"
            echo "$HOURLY" | jq '.hours[0] | keys'
        fi
    fi
else
    echo "❌ FAIL — not wrapped"
    echo "$HOURLY" | jq 'type'
fi

# Validate incidents ranking shape
echo -n "Incidents wrapped in {incidents: [...]}... "
INCIDENTS=$(curl -s -H "$(auth_header)" "$BASE/costs/incidents/ranking?day=1&limit=5")
if echo "$INCIDENTS" | jq -e '.incidents | type == "array"' > /dev/null 2>&1; then
    echo "✅ OK"
    COUNT=$(echo "$INCIDENTS" | jq '.incidents | length')
    echo "  → $COUNT incident records"
    if [ "$COUNT" -gt 0 ]; then
        echo -n "  → First item has incident_id, type, total_eur, direct_eur, response_eur... "
        if echo "$INCIDENTS" | jq -e '.incidents[0] | .incident_id != null and .total_eur != null' > /dev/null 2>&1; then
            echo "✅ OK"
        else
            echo "❌ FAIL"
            echo "$INCIDENTS" | jq '.incidents[0] | keys'
        fi
    fi
else
    echo "❌ FAIL — not wrapped"
    echo "$INCIDENTS" | jq 'type'
fi

# Validate PnL shape
echo -n "PnL has day, by_category, cost_records... "
PNL=$(curl -s -H "$(auth_header)" "$BASE/costs/pnl?day=1")
if echo "$PNL" | jq -e '.day != null and .by_category != null and .cost_records != null' > /dev/null 2>&1; then
    echo "✅ OK"
else
    echo "❌ FAIL — missing fields"
    echo "$PNL" | jq 'keys'
fi

echo ""
echo "Done."

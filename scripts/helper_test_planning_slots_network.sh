#!/usr/bin/env bash
# helper_test_planning_slots_network.sh — Hit planning-service slot allocation and
# network resilience endpoints and verify response shapes.
#
# Usage:
#   bash scripts/helper_test_planning_slots_network.sh [BASE_URL]
#
# Arguments:
#   BASE_URL  Planning service base URL (default: http://localhost:8009/api/v1/planning)
#
# Requirements:
#   - curl and jq installed
#   - planning-service running with BTS data mounted

set -euo pipefail

BASE="${1:-http://localhost:8009/api/v1/planning}"

echo "═══════════════════════════════════════════════════════"
echo "  Planning Slots & Network Endpoint Test — $BASE"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Slot allocation ─────────────────────────────────────────

echo "── POST /slots/allocate (fcfs) ──"
RESULT=$(curl -s -X POST "$BASE/slots/allocate" \
  -H "Content-Type: application/json" \
  -d '{"requests": [
    {"id":"s1","airline":"BA","requested_hour":8,"priority":3},
    {"id":"s2","airline":"LH","requested_hour":8,"priority":1},
    {"id":"s3","airline":"AF","requested_hour":8,"priority":1},
    {"id":"s4","airline":"FR","requested_hour":9,"priority":1}
  ], "strategy":"fcfs", "hourly_capacity":60}')
echo "$RESULT" | jq '{strategy, total_displacement_minutes, allocations_count: (.allocations | length)}'
echo ""

echo "── POST /slots/allocate (optimised) ──"
RESULT=$(curl -s -X POST "$BASE/slots/allocate" \
  -H "Content-Type: application/json" \
  -d '{"requests": [
    {"id":"s1","airline":"BA","requested_hour":8,"priority":3},
    {"id":"s2","airline":"LH","requested_hour":8,"priority":1},
    {"id":"s3","airline":"AF","requested_hour":8,"priority":1},
    {"id":"s4","airline":"FR","requested_hour":8,"priority":1},
    {"id":"s5","airline":"EK","requested_hour":8,"priority":2},
    {"id":"s6","airline":"UA","requested_hour":8,"priority":1},
    {"id":"s7","airline":"DL","requested_hour":8,"priority":1},
    {"id":"s8","airline":"AA","requested_hour":8,"priority":1},
    {"id":"s9","airline":"KL","requested_hour":8,"priority":1},
    {"id":"s10","airline":"IB","requested_hour":8,"priority":1},
    {"id":"s11","airline":"TP","requested_hour":8,"priority":1}
  ], "strategy":"optimised", "hourly_capacity":10}')
echo "$RESULT" | jq '{strategy, total_displacement_minutes, max_displacement_minutes, unallocated_count}'
echo ""

echo "── POST /slots/compare ──"
RESULT=$(curl -s -X POST "$BASE/slots/compare" \
  -H "Content-Type: application/json" \
  -d '{"requests": [
    {"id":"s1","airline":"BA","requested_hour":8,"priority":3},
    {"id":"s2","airline":"LH","requested_hour":8,"priority":1},
    {"id":"s3","airline":"AF","requested_hour":8,"priority":1},
    {"id":"s4","airline":"FR","requested_hour":8,"priority":1},
    {"id":"s5","airline":"EK","requested_hour":8,"priority":2},
    {"id":"s6","airline":"UA","requested_hour":8,"priority":1},
    {"id":"s7","airline":"DL","requested_hour":8,"priority":1},
    {"id":"s8","airline":"AA","requested_hour":8,"priority":1},
    {"id":"s9","airline":"KL","requested_hour":8,"priority":1},
    {"id":"s10","airline":"IB","requested_hour":8,"priority":1},
    {"id":"s11","airline":"TP","requested_hour":8,"priority":1}
  ], "hourly_capacity":10}')
echo "$RESULT" | jq '.summary'
echo ""

# ── Network resilience ──────────────────────────────────────

echo "── GET /network/dependency ──"
RESULT=$(curl -s "$BASE/network/dependency")
echo "$RESULT" | jq '{herfindahl_index, concentration_rating, effective_airlines, top_5: [.airlines[:5][] | {code: .airline_code, share: .movement_share_pct}]}'
echo ""

echo "── POST /network/disruption (remove top airline) ──"
TOP_AIRLINE=$(echo "$RESULT" | jq -r '.airlines[0].airline_code')
echo "  Simulating removal of $TOP_AIRLINE..."
DISRUPT=$(curl -s -X POST "$BASE/network/disruption" \
  -H "Content-Type: application/json" \
  -d "{\"airline\":\"$TOP_AIRLINE\",\"reduction_pct\":100}")
echo "$DISRUPT" | jq '{airline_code, lost_daily_departures, lost_daily_passengers, exclusive_routes_lost, revenue_impact_pct, new_herfindahl}'
echo ""

echo "── POST /network/diversify ──"
RESULT=$(curl -s -X POST "$BASE/network/diversify" \
  -H "Content-Type: application/json" \
  -d '{"target_hhi":0.10,"max_recommendations":5}')
echo "$RESULT" | jq '{current_hhi, diversification_needed, recommendations: [.recommendations[] | {dest: .destination_iata, demand: .estimated_daily_demand, freq: .recommended_frequency, aircraft: .recommended_aircraft}]}'
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  All tests completed"
echo "═══════════════════════════════════════════════════════"

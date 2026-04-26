#!/usr/bin/env bash
# Diagnose passenger, baggage, and flight flows
# Usage: bash scripts/helper_diagnose_flows.sh

set -euo pipefail

GATEWAY="http://localhost:3000"
FLIGHT_SVC="http://localhost:8001"
PAX_SVC="http://localhost:8002"
BAG_SVC="http://localhost:8003"

echo "=== Flight Status Distribution ==="
curl -s "$FLIGHT_SVC/api/v1/flights?limit=200" | python3 -c "
import json, sys
data = json.load(sys.stdin)
flights = data.get('flights', [])
status_counts = {}
for f in flights:
    s = f.get('status', 'unknown')
    status_counts[s] = status_counts.get(s, 0) + 1
for s, c in sorted(status_counts.items()):
    print(f'  {s}: {c}')
print(f'  TOTAL: {len(flights)}')
# Show boarding flights with details
boarding = [f for f in flights if f['status'] == 'boarding']
if boarding:
    print()
    print('--- Boarding flights (first 10):')
    for f in boarding[:10]:
        print(f'  {f[\"flight_number\"]} | delay={f.get(\"delay_minutes\",0)}min | pax={f.get(\"pax_count\",0)}/{f.get(\"seat_capacity\",0)} | gate={f.get(\"gate_id\",\"?\")}')
"

echo ""
echo "=== Passenger Status Distribution ==="
for status in booked checked_in security_queue airside at_gate boarded deplaning baggage_claim departed_airport; do
    count=$(curl -s "$PAX_SVC/api/v1/passengers?status=$status&limit=1" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "?")
    echo "  $status: $count"
done

echo ""
echo "=== Baggage Status Distribution ==="
curl -s "$BAG_SVC/api/v1/flow/summary" | python3 -c "
import json, sys
data = json.load(sys.stdin)
by_status = data.get('by_status', {})
total = data.get('total_in_system', 0)
for s, c in sorted(by_status.items()):
    print(f'  {s}: {c}')
print(f'  total_in_system: {total}')
print(f'  flagged_active: {data.get(\"flagged_active\", 0)}')
print(f'  system_failures: {data.get(\"system_failures_active\", 0)}')
"

echo ""
echo "=== Boarding Flights Detailed Check (first 5) ==="
curl -s "$FLIGHT_SVC/api/v1/flights?status=boarding&limit=5" | python3 -c "
import json, sys, subprocess
data = json.load(sys.stdin)
flights = data.get('flights', [])
for f in flights:
    fid = f['id']
    fn = f['flight_number']
    detail_raw = subprocess.run(['curl', '-s', f'http://localhost:8001/api/v1/flights/{fid}'], capture_output=True, text=True).stdout
    try:
        detail = json.loads(detail_raw)
        pax = detail.get('passengers', {})
        bag = detail.get('baggage', {})
        print(f'  {fn}: boarded={pax.get(\"boarded\",0)}/{pax.get(\"total\",0)} | at_gate={pax.get(\"at_gate\",0)} | airside={pax.get(\"airside\",0)} | bag_loaded={bag.get(\"loaded\",0)}/{bag.get(\"total_items\",0)} | delay={f.get(\"delay_minutes\",0)}min')
    except Exception as e:
        print(f'  {fn}: error getting details: {e}')
"

echo ""
echo "=== Sim Clock Status ==="
curl -s "http://localhost:8006/api/v1/status" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  sim_time: {data.get(\"sim_time\", \"?\")}')
print(f'  state: {data.get(\"state\", \"?\")}')
print(f'  speed: {data.get(\"speed_multiplier\", \"?\")}x')
print(f'  day: {data.get(\"day_of_sim\", \"?\")}')
"

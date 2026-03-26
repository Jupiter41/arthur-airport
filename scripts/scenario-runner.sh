#!/usr/bin/env bash
# scenario-runner.sh — CLI wrapper for the scenario engine REST API
#
# Usage:
#   ./scripts/scenario-runner.sh list                     List available scenarios
#   ./scripts/scenario-runner.sh show <name>              Show scenario definition
#   ./scripts/scenario-runner.sh run <name> [--speed N]   Run a scenario
#   ./scripts/scenario-runner.sh active                   Check active scenario
#   ./scripts/scenario-runner.sh stop                     Stop active scenario
#   ./scripts/scenario-runner.sh results                  List all past results
#   ./scripts/scenario-runner.sh result <run_id>          Get detailed result
#
# Environment:
#   SIM_URL   Base URL (default: http://localhost:8006)

set -euo pipefail

SIM_URL="${SIM_URL:-http://localhost:8006}"
BASE="${SIM_URL}/api/v1/scenarios"

_json() { python3 -m json.tool 2>/dev/null || cat; }

case "${1:-help}" in
  list)
    echo "=== Available Scenarios ==="
    curl -sS "${BASE}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d['scenarios']:
    print(f\"  {s['name']}\")
    print(f\"    Duration: {s['duration_sim_minutes']} min | Events: {s['event_count']} | Outcomes: {s['outcome_count']}\")
    print()
"
    ;;

  show)
    NAME="${2:?Usage: scenario-runner.sh show <name>}"
    ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${NAME}'))")
    curl -sS "${BASE}/${ENCODED}" | _json
    ;;

  run)
    NAME="${2:?Usage: scenario-runner.sh run <name> [--speed N]}"
    SPEED=600
    shift 2
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --speed) SPEED="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
      esac
    done
    ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${NAME}'))")
    echo "Starting scenario: ${NAME} (speed: ${SPEED}x)"
    RESULT=$(curl -sS -X POST "${BASE}/${ENCODED}/run" \
      -H "Content-Type: application/json" \
      -d "{\"speed\": ${SPEED}}")
    echo "${RESULT}" | _json

    # Extract run_id for polling
    RUN_ID=$(echo "${RESULT}" | python3 -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
    echo ""
    echo "Run ID: ${RUN_ID}"
    echo "Polling for completion..."
    echo ""

    while true; do
      ACTIVE=$(curl -sS "${BASE}/active")
      IS_ACTIVE=$(echo "${ACTIVE}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('active', False))")
      if [ "${IS_ACTIVE}" = "False" ]; then
        break
      fi
      SNAP=$(echo "${ACTIVE}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
m = d.get('latest_metrics')
if m:
    print(f\"  offset={m['offset_minutes']}m | delayed={m['flights_delayed_current']} | incidents={m['incident_count_active']} | holding={m['holding_stack_depth']}\")
else:
    print('  waiting for first snapshot...')
")
      echo "${SNAP}"
      sleep 2
    done

    echo ""
    echo "=== Scenario Complete ==="
    curl -sS "${BASE}/results/${RUN_ID}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"Status:  {d['status']}\")
print(f\"Passed:  {d['passed']}\")
print(f\"Events:  {d['events_injected']}\")
print(f\"Snaps:   {len(d['metric_snapshots'])}\")
print()
print('Outcomes:')
for o in d['outcome_results']:
    s = 'PASS' if o['passed'] else 'FAIL'
    print(f\"  [{s}] {o['metric']}: {o['condition']} (actual: {o['actual']})\")
print()
print(f\"Summary: {d['summary']}\")
"
    ;;

  active)
    curl -sS "${BASE}/active" | _json
    ;;

  stop)
    curl -sS -X POST "${BASE}/active/stop" | _json
    ;;

  results)
    echo "=== Past Results ==="
    curl -sS "${BASE}/results" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if not d['results']:
    print('  No results yet.')
else:
    for r in d['results']:
        p = 'PASS' if r['passed'] else 'FAIL'
        print(f\"  [{p}] {r['scenario_name']} (run={r['run_id']})\")
        print(f\"        {r['summary']}\")
        print()
"
    ;;

  result)
    RUN_ID="${2:?Usage: scenario-runner.sh result <run_id>}"
    curl -sS "${BASE}/results/${RUN_ID}" | _json
    ;;

  help|*)
    echo "Usage: scenario-runner.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  list                     List available scenarios"
    echo "  show <name>              Show scenario definition"
    echo "  run <name> [--speed N]   Run a scenario (default speed: 600x)"
    echo "  active                   Check active scenario status"
    echo "  stop                     Stop active scenario"
    echo "  results                  List past results"
    echo "  result <run_id>          Get detailed result"
    echo ""
    echo "Environment:"
    echo "  SIM_URL   Base URL (default: http://localhost:8006)"
    ;;
esac

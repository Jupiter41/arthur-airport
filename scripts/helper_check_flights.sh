#!/usr/bin/env bash
# helper_check_flights.sh — Quick diagnostic for flight states
# Usage: ./scripts/helper_check_flights.sh
#
# Shows:
#   1. Flight status distribution (departures vs arrivals)
#   2. Boarding flights with highest delays
#   3. Cancelled flight count and reasons

set -euo pipefail

NEO4J_CONTAINER="${NEO4J_CONTAINER:-arthur-airport-neo4j-1}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASS="${NEO4J_PASS:-art-digital-twin}"

cypher() {
  docker exec "$NEO4J_CONTAINER" cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASS" "$1"
}

echo "=== Departure Flight Status ==="
cypher "MATCH (f:Flight) WHERE f.direction = 'departure' RETURN f.status AS status, count(f) AS cnt ORDER BY cnt DESC"

echo ""
echo "=== Arrival Flight Status ==="
cypher "MATCH (f:Flight) WHERE f.direction = 'arrival' RETURN f.status AS status, count(f) AS cnt ORDER BY cnt DESC"

echo ""
echo "=== Top 10 Boarding Flights by Delay ==="
cypher "MATCH (f:Flight) WHERE f.status = 'boarding' AND f.direction = 'departure' RETURN f.flight_number AS fn, f.gate_id AS gate, f.delay_minutes AS delay, f.pax_count AS pax ORDER BY delay DESC LIMIT 10"

echo ""
echo "=== Kafka Consumer Lag (sim.clock) ==="
docker exec arthur-airport-kafka-1 kafka-consumer-groups \
  --bootstrap-server localhost:9092 \
  --describe --all-groups 2>/dev/null \
  | grep "sim.clock" || echo "(no consumers found)"

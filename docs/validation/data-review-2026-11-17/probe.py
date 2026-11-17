"""Read-only closure probes; run on the flight-service container's network."""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from neo4j import GraphDatabase, READ_ACCESS


def get(url, token=None):
    start = time.monotonic()
    try:
        headers = {"Authorization": "Bearer " + token} if token else {}
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            body = response.read().decode()
            try:
                body = json.loads(body)
            except ValueError:
                pass
            return {"status": response.status, "elapsed_ms": round((time.monotonic() - start) * 1000, 1), "body": body}
    except Exception as error:
        return {"error": str(error), "elapsed_ms": round((time.monotonic() - start) * 1000, 1)}


driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://neo4j:7687"), auth=(
    os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "art-digital-twin")))
report = {"observed_at": datetime.now(timezone.utc).isoformat(), "queries": {}, "http": {}}


def query(name, cypher, **params):
    start = time.monotonic()
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            rows = session.run(cypher, **params).data()
        report["queries"][name] = {"elapsed_ms": round((time.monotonic() - start) * 1000, 1), "rows": rows}
        return rows
    except Exception as error:
        report["queries"][name] = {"error": str(error)}
        return []


clock = get("http://sim-orchestrator:8006/api/v1/sim/status")
report["http"]["sim"] = clock
now = datetime.fromisoformat(clock["body"]["sim_time"]).replace(tzinfo=None)
cutoff = (now - timedelta(hours=24)).isoformat()
report["sim_time"] = now.isoformat()
query("seed_days", "MATCH (d:SeedDay) RETURN d.id AS day, d.ready AS ready ORDER BY day")
query("seed_batches", "MATCH (b:SeedBatch) RETURN b.owner AS owner, b.pending AS pending, count(*) AS n, min(b.sim_time) AS oldest, max(b.sim_time) AS newest ORDER BY owner, pending")
query("checkpoints", "MATCH (s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq OR s:CostRuntime RETURN labels(s) AS labels, s.last_tick_sim_time AS tick, size(s.document) AS bytes")
for owner in ("Flight", "Passenger", "Baggage", "Cost"):
    query(owner + "_outbox", f"MATCH (o:{owner}Outbox) RETURN count(o) AS n")
for label in ("Passenger", "PassengerArchive", "Baggage", "BaggageArchive", "ScanEvent", "ScanEventArchive", "Flight", "CostInbox"):
    query(label + "_counts", f"MATCH (n:{label}) RETURN n.status AS status, count(*) AS n")
query("arrival_bag_links_by_day", """
MATCH (f:Flight {direction:'arrival'})<-[:LOADED_ON]-(b)
WHERE b:Baggage OR b:BaggageArchive
WITH f, b, EXISTS { MATCH ()-[:CARRIES]->(b) } AS linked
RETURN substring(f.scheduled_time,0,10) AS day, b.status AS status, linked, count(b) AS n
ORDER BY day, status, linked
""")
query("stranded_arrival_holds", """
MATCH (b:Baggage {status:'in_hold'})-[:LOADED_ON]->(f:Flight {direction:'arrival'})
WHERE f.status IN ['at_gate','arrived','completed']
RETURN substring(f.scheduled_time,0,10) AS day, f.status AS flight_status,
       count(b) AS bags, min(f.actual_time) AS oldest_flight_time
ORDER BY day
""")
query("phantom_airborne", """
MATCH (p:Passenger {status:'airborne'})-[:ON_FLIGHT]->(f:Flight {direction:'arrival',status:'scheduled'})
RETURN substring(f.scheduled_time,0,10) AS day, count(p) AS n ORDER BY day
""")
query("departure_holds_without_screening", """
MATCH (f:Flight {direction:'departure'})<-[:LOADED_ON]-(b)
WHERE (b:Baggage OR b:BaggageArchive) AND b.status = 'in_hold'
  AND NOT EXISTS { MATCH (b)-[:SCANNED_AT]->(s) WHERE s.zone STARTS WITH 'screening' }
RETURN substring(f.scheduled_time,0,10) AS day, count(b) AS n ORDER BY day
""")
query("passenger_flight_cardinality", """
MATCH (p:Passenger) OPTIONAL MATCH (p)-[r:ON_FLIGHT]->()
WITH p, count(r) AS n WHERE n <> 1 RETURN n AS links, p.status AS status, count(p) AS passengers
""")
query("connection_integrity", """
MATCH (p:Passenger {connection:true})
OPTIONAL MATCH (f:Flight {id:p.connection_flight_id})
RETURN p.status AS status, p.connection_flight_id IS NULL AS missing_id,
       f IS NULL AS missing_flight, count(p) AS n
""")
query("passenger_terminal_retention_backlog", """
MATCH (p:Passenger) WHERE
 (p.status='departed_airport' AND p.departed_airport_at < $cutoff)
 OR (p.status='missed_flight' AND p.missed_flight_at < $cutoff)
RETURN p.status AS status, count(p) AS n, min(coalesce(p.departed_airport_at,p.missed_flight_at)) AS oldest
""", cutoff=cutoff)
query("arrival_claim_duration", """
MATCH (p) WHERE (p:Passenger OR p:PassengerArchive) AND p.baggage_claim_at IS NOT NULL
 AND p.departed_airport_at IS NOT NULL
WITH substring(p.departed_airport_at,0,10) AS day,
 duration.inSeconds(datetime(p.baggage_claim_at),datetime(p.departed_airport_at)).seconds/60.0 AS mins
RETURN day, count(*) AS n, min(mins) AS min, percentileCont(mins,0.5) AS p50,
       percentileCont(mins,0.9) AS p90, sum(CASE WHEN mins >= 45 THEN 1 ELSE 0 END) AS timeout_sized
ORDER BY day
""")
query("bag_claim_missing_passenger", """
MATCH (b:Baggage) WHERE b.status IN ['arrived','on_carousel','collected']
OPTIONAL MATCH (p)-[:CARRIES]->(b)
RETURN b.status AS status, p IS NULL AS missing_passenger, count(b) AS n
""")
query("overdue_flights", """
MATCH (f:Flight) WHERE NOT f.status IN ['arrived','completed','cancelled','diverted']
 AND f.scheduled_time < $cutoff
RETURN f.direction AS direction, f.status AS status, count(f) AS n, min(f.scheduled_time) AS oldest
""", cutoff=cutoff)
query("stuck_incidents", "MATCH (i:Incident) WHERE i.status IN ['active','contained'] AND i.ttr_remaining <= 0 RETURN i.type AS type, i.status AS status, count(i) AS n")
query("cost_future_records", "MATCH (c:CostRecord) WHERE c.sim_time > $future RETURN count(c) AS n, max(c.sim_time) AS latest", future=(now + timedelta(days=1)).isoformat())
query("flight_delay_distribution", """
MATCH (f:Flight {direction:'departure'}) WHERE f.status IN ['airborne','arrived','completed']
RETURN substring(f.scheduled_time,0,10) AS day, count(f) AS n, avg(f.delay_minutes) AS mean_delay,
 sum(CASE WHEN f.delay_minutes>=30 THEN 1 ELSE 0 END) AS delayed_30,
 sum(CASE WHEN f.delay_reason='boarding_incomplete' THEN 1 ELSE 0 END) AS boarding_incomplete ORDER BY day
""")
for name, url in {
    "passengers": "http://passenger-service:8002/api/v1/flow/summary",
    "baggage": "http://baggage-service:8003/api/v1/flow/summary",
    "weather_source": "http://weather-service:8004/api/v1/weather/source",
    "adsb_source": "http://flight-service:8001/api/v1/flights/adsb/source",
    "flights": "http://flight-service:8001/api/v1/flights?limit=1",
    "gateway_health": "http://api-gateway:3000/health",
}.items():
    report["http"][name] = get(url)
for owner, port in [("flight",8001),("passenger",8002),("baggage",8003),("analysis",8007)]:
    result = get(f"http://{owner}-service:{port}/metrics")
    if isinstance(result.get("body"), str):
        result["body"] = "\n".join(line for line in result["body"].splitlines() if not line.startswith("#") and any(
            term in line for term in ["service_tick_processing_seconds", "service_tick_phase_seconds_sum", "service_tick_phase_seconds_count", "outbox", "consumer_lag", "gateway_ws"]))
    report["http"][owner + "_metrics"] = result
report["source_hashes"] = {path: hashlib.sha256(open(path,"rb").read()).hexdigest() for path in [
    "/app/kafka/consumer.py", "/app/_common/seed_requests.py", "/app/_common/flight_view.py"]}
driver.close()
print(json.dumps(report, indent=2, default=str))

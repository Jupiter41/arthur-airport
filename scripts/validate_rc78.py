"""Record RC7/RC8 cold-start, inbound and 23:30/midnight evidence on a disposable stack."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import time
from pathlib import Path

from neo4j import GraphDatabase
import requests

from scripts.validate_stack import readiness


def snapshot(driver) -> dict:
    def query(cypher):
        with driver.session() as session:
            return [dict(row) for row in session.run(cypher)]

    return {
        "clock": query("MATCH (s:SimState {id:'airport'}) RETURN properties(s) AS state"),
        "days": query("MATCH(d:SeedDay) RETURN d.id AS day, d.ready AS ready ORDER BY day"),
        "pending": query("MATCH(b:SeedBatch) RETURN b.owner AS owner, b.pending AS pending, count(*) AS n ORDER BY owner, pending"),
        "bag_links": query("MATCH(b) WHERE b:Baggage OR b:BaggageArchive RETURN count(b) AS bags, "
                           "sum(CASE WHEN EXISTS { (p)-[:CARRIES]->(b) } THEN 0 ELSE 1 END) AS anonymous"),
        "passenger_links": query("MATCH(p:Passenger) RETURN count(p) AS passengers, "
                                 "sum(CASE WHEN COUNT { (p)-[:ON_FLIGHT]->() } = 1 THEN 0 ELSE 1 END) AS invalid"),
        "phantom_airborne": query("MATCH(p:Passenger {status:'airborne'})-[:ON_FLIGHT]->(f:Flight {direction:'arrival',status:'scheduled'}) RETURN count(p) AS n"),
        "transfers": query("MATCH(p:Passenger) WHERE p.inbound_flight_id IS NOT NULL RETURN count(p) AS passengers"),
        "transfer_bags": query("MATCH(b:Baggage) WHERE b.inbound_flight_id IS NOT NULL RETURN count(b) AS bags"),
        "claim_exits": query("MATCH(p:Passenger) WHERE p.baggage_claim_at IS NOT NULL AND p.departed_airport_at IS NOT NULL "
                             "RETURN count(p) AS n, sum(CASE WHEN duration.between(datetime(p.baggage_claim_at), "
                             "datetime(p.departed_airport_at)).minutes < 45 THEN 1 ELSE 0 END) AS early"),
        "observations": query("MATCH(o:PassengerBaggageObservation) RETURN count(o) AS n, count(o.collected_at) AS collected"),
        "checkpoints": query("MATCH(s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq "
                             "RETURN labels(s) AS owner, s.last_tick_sim_time AS tick"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "art-digital-twin"))
    samples = []
    try:
        while time.monotonic() < deadline:
            services = readiness()
            if all(row["ready"] for row in services.values()):
                break
            time.sleep(2)
        else:
            raise AssertionError(f"Cold stack readiness failed: {services}")
        initial = snapshot(driver)
        print(json.dumps({"ready": services, "initial": initial}), flush=True)
        days = initial["days"]
        assert days and days[0]["ready"], "Real startup must create a ready manifest"
        day_two = (datetime.fromisoformat(days[0]["day"]) + timedelta(days=1)).date().isoformat()
        target = datetime.fromisoformat(day_two + "T00:30:00")
        next_sample = None
        while time.monotonic() < deadline:
            status = requests.get("http://localhost:8006/api/v1/sim/status", timeout=10).json()
            now = datetime.fromisoformat(status["sim_time"].replace("Z", "+00:00")).replace(tzinfo=None)
            if next_sample is None or now >= next_sample:
                row = snapshot(driver)
                samples.append(row)
                print(json.dumps({"sim_time": now.isoformat(), "days": row["days"], "pending": row["pending"]}), flush=True)
                next_sample = now + timedelta(hours=2)
            if now >= target:
                # Let the owners finish their bounded watermark lag before judging the graph.
                paused = requests.post("http://localhost:8006/api/v1/sim/pause", timeout=10)
                paused.raise_for_status()
                now = datetime.fromisoformat(paused.json()["sim_time"].replace("Z", "+00:00")).replace(tzinfo=None)
                for _ in range(60):
                    final = snapshot(driver)
                    if all(r["tick"] and datetime.fromisoformat(r["tick"]) >= now for r in final["checkpoints"]):
                        break
                    time.sleep(1)
                assert len(final["checkpoints"]) == 3
                assert all(r["tick"] and datetime.fromisoformat(r["tick"]) >= now for r in final["checkpoints"])
                assert any(d["day"] == day_two and d["ready"] for d in final["days"])
                assert not any(b["pending"] for b in final["pending"])
                assert final["bag_links"][0]["bags"] > 0 and final["bag_links"][0]["anonymous"] == 0
                assert final["passenger_links"][0]["invalid"] == 0
                assert final["phantom_airborne"][0]["n"] == 0
                assert final["claim_exits"][0]["early"] > 0
                assert final["transfers"][0]["passengers"] > 0
                assert final["transfer_bags"][0]["bags"] > 0
                args.report.write_text(json.dumps({"readiness": services, "initial": initial,
                                                  "samples": samples, "final": final}, indent=2))
                print(json.dumps({"passed": True, "report": str(args.report), "final": final}), flush=True)
                return
            time.sleep(2)
        raise AssertionError("Simulation did not reach the next-day boundary within the validation budget")
    finally:
        driver.close()


if __name__ == "__main__":
    main()

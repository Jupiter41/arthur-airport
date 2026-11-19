"""Disposable full-stack RC11 interruption and six-hour owner-outage evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import time

from neo4j import GraphDatabase
import requests

from scripts.validate_stack import readiness


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def status() -> dict:
    response = requests.get("http://localhost:8006/api/v1/sim/status", timeout=15)
    response.raise_for_status()
    return response.json()


def compose(*args: str) -> None:
    result = subprocess.run(["docker", "compose", *args], text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def until(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except requests.RequestException:
            pass
        time.sleep(1)
    raise AssertionError("RC11 validation condition timed out")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    until(lambda: all(row["ready"] for row in readiness().values()), 300)
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "art-digital-twin"))

    def query(cypher):
        with driver.session() as session:
            return [dict(r) for r in session.run(cypher)]

    def sample():
        current = status()
        assert not current["paused"], "Recovery must not require operator resume"
        return {"clock":current["sim_time"], "watermarks":current["watermarks"],
                "checkpoints":query("MATCH(s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq "
                                    "RETURN labels(s) AS owner,s.last_tick_sim_time AS at"),
                "days":query("MATCH(d:SeedDay) RETURN d.id AS day,d.ready AS ready ORDER BY day"),
                "seed_times":query("MATCH(b:SeedBatch) RETURN b.sim_time AS at,b.pending AS pending,count(*) AS n ORDER BY at")}
    try:
        initial = sample()
        print(json.dumps({"phase":"initial", "clock":initial["clock"]}), flush=True)
        until(lambda: not query("MATCH(b:SeedBatch {pending:true}) RETURN b LIMIT 1"))
        before_database = sample()
        compose("pause", "neo4j")
        try:
            time.sleep(2)
        finally:
            compose("unpause", "neo4j")
        limit = iso(before_database["clock"]) + timedelta(minutes=3)
        until(lambda: iso(status()["sim_time"]) >= limit)
        after_database = sample()
        print(json.dumps({"phase":"database_recovered", "clock":after_database["clock"]}), flush=True)
        compose("stop", "passenger-service", "baggage-service")
        before_outage = sample()
        target = iso(before_outage["clock"]) + timedelta(hours=6)
        until(lambda: iso(status()["sim_time"]) >= target, 180)
        during_outage = sample()
        print(json.dumps({"phase":"six_hour_outage", "clock":during_outage["clock"]}), flush=True)
        for row in during_outage["checkpoints"]:
            if row["owner"][0] in ("PassengerRuntime", "BaggageOutboxSeq"):
                assert iso(during_outage["clock"]) - iso(row["at"]) >= timedelta(hours=6)
        # Use the normal owner tick budget for recovery; 600x is only the
        # configurable backlog-accumulation phase, not a throughput benchmark.
        speed = requests.patch("http://localhost:8006/api/v1/sim/speed", json={"speed_multiplier":60}, timeout=15)
        speed.raise_for_status()
        compose("start", "passenger-service", "baggage-service")
        started = time.monotonic()
        samples = []
        def caught_up():
            row = sample()
            samples.append(row)
            return all(v["at"] and iso(v["at"]) >= target
                       and iso(row["clock"]) - iso(v["at"]) <= timedelta(minutes=5)
                       for v in row["checkpoints"])
        until(caught_up, 240)
        until(lambda: all(row["ready"] for row in readiness().values()))
        elapsed = time.monotonic() - started
        print(json.dumps({"phase":"owners_caught_up", "seconds":elapsed}), flush=True)
        paused = requests.post("http://localhost:8006/api/v1/sim/pause", timeout=15)
        paused.raise_for_status()
        end = iso(paused.json()["sim_time"])
        until(lambda: all(v["at"] and iso(v["at"]) >= end for v in query(
            "MATCH(s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq "
            "RETURN s.last_tick_sim_time AS at")))
        final = {"clock":paused.json()["sim_time"], "checkpoints":query(
            "MATCH(s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq "
            "RETURN labels(s) AS owner,s.last_tick_sim_time AS at"), "readiness":readiness()}
        # Read this fresh project's complete clock stream inside its network.
        code = '''import json
from confluent_kafka import Consumer, TopicPartition
c=Consumer({"bootstrap.servers":"kafka:9092","group.id":"rc11-evidence","enable.auto.commit":False})
tp=TopicPartition("sim.clock",0)
low,high=c.get_watermark_offsets(tp,timeout=15)
c.assign([TopicPartition(tp.topic,0,low)])
rows=[]
while c.position([tp])[0].offset < high:
    for m in c.consume(1000,timeout=1):
        if not m.error():
            d=json.loads(m.value())
            if d.get("event_type")=="SimClockTick":
                rows.append({"at":d["sim_time"],"produced_at":d["produced_at"],"step":d["payload"]["step_minutes"]})
c.close()
print(json.dumps(rows))'''
        result = subprocess.run(["docker","compose","exec","-T","sim-orchestrator","python","-c",code],
                                text=True,capture_output=True,timeout=60)
        assert result.returncode == 0, result.stderr
        ticks = json.loads(result.stdout.strip().splitlines()[-1])
        for previous, current in zip(ticks, ticks[1:]):
            assert iso(current["at"]) - iso(previous["at"]) == timedelta(minutes=current["step"])
        boundary = [t for t in ticks if "T23:2" in t["at"] or "T23:3" in t["at"] or "T00:0" in t["at"]]
        assert any("T23:30:" in t["at"] for t in ticks) and any("T00:00:" in t["at"] for t in ticks)
        log = subprocess.run(["docker","compose","logs","--no-color","sim-orchestrator","passenger-service","baggage-service"],
                             text=True,capture_output=True,timeout=30)
        for marker in ("MemoryPoolOutOfMemory", "Clock checkpoint failed; simulation paused", "Day start barrier failed"):
            assert marker not in log.stdout, marker
        report = {"initial":initial,"before_database_pause":before_database,"after_database_pause":after_database,
                  "before_owner_outage":before_outage,"six_hour_outage":during_outage,"recovery_samples":samples,
                  "recovery_wall_seconds":elapsed,"final":final,"tick_count":len(ticks),"boundary_ticks":boundary,
                  "continuous_clock_stream":True,"no_oom_or_auto_pause":True}
        args.report.write_text(json.dumps(report,indent=2))
        print(json.dumps({"passed":True,"ticks":len(ticks),"recovery_seconds":elapsed,"report":str(args.report)}))
    finally:
        driver.close()


if __name__ == "__main__":
    main()

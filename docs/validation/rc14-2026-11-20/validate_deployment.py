"""Validate the original airport after RC14 rollout through normal controls."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import time

from neo4j import GraphDatabase
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROJECT = "art-ldt-g6"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "docker-compose.yml"),
           "-f", str(OUT / "rollout.compose.yml")]
http = requests.Session()
report = {}
observer = None
facts_path = Path("/tmp/rc14-owner-facts.ndjson")
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "art-digital-twin"))


def save(key, value):
    report[key] = value
    (OUT / "live-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"phase": key, "result": value}), flush=True)


def call(path, method="GET", body=None):
    response = http.request(method, "http://localhost:3000" + path, json=body, timeout=15)
    response.raise_for_status()
    return response.json()


def status():
    response = requests.get("http://localhost:8006/api/v1/sim/status", timeout=10)
    response.raise_for_status()
    return response.json()


def sim_time():
    return datetime.fromisoformat(status()["sim_time"].replace("Z", "+00:00")).replace(tzinfo=None)


def wait(check, timeout=1800):
    deadline = time.monotonic() + timeout
    last = None
    log_at = 0
    while time.monotonic() < deadline:
        try:
            return check()
        except (requests.RequestException, AssertionError) as error:
            last = error
            if time.monotonic() >= log_at:
                print(json.dumps({"waiting": str(error)}), flush=True)
                log_at = time.monotonic() + 30
            time.sleep(1)
    raise AssertionError(f"Timed out: {last}")


def query(cypher, **parameters):
    return [dict(row) for row in driver.execute_query(cypher, parameters_=parameters).records]


def ready():
    response = requests.get("http://localhost:3000/ready", timeout=15)
    assert response.status_code == 200, f"gateway ready={response.status_code} {response.text[:300]}"
    return response.json()


def compose(*args):
    subprocess.run([*COMPOSE, *args], check=True, cwd=ROOT)


def verify_builds(name):
    subprocess.run([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/verify_builds.py"),
                    "--project", PROJECT, "--manifest", str(OUT / "deployment-lock.json"),
                    "--revision", json.loads((OUT / "deployment-lock.json").read_text())["revision"],
                    "--report", str(OUT / name)], check=True, cwd=ROOT)


def owner_aligned():
    value = status()
    assert not value["paused"], "Unexpected automatic clock pause"
    marks = value["watermarks"]
    assert len(marks) == 3 and all(not m["stale"] and m["lag_minutes"] <= 5 for m in marks.values()), marks
    return value


def start_observer(day):
    code = r'''
import json,sys,uuid,os
from confluent_kafka import Consumer
prefix=sys.argv[1]+":"
c=Consumer({"bootstrap.servers":"kafka:9092","group.id":"rc14-audit-"+uuid.uuid4().hex,"auto.offset.reset":"latest","enable.auto.commit":False})
def assigned(c,parts):
 c.assign(parts)
 print(json.dumps({"observer_ready":True,"pid":os.getpid()}),flush=True)
c.subscribe(["flights.events","passengers.events","baggage.events"],on_assign=assigned)
fields={"FlightsScheduled":"flights","PassengersSeeded":"passengers","BaggageSeeded":"baggage"}
while True:
 m=c.poll(0.5)
 if m is None or m.error():continue
 d=json.loads(m.value());p=d.get("payload",{});kind=d.get("event_type")
 if kind in fields and str(p.get("seed_batch_id","")).startswith(prefix):
  rows=[{k:v for k,v in row.items() if k in {"id","flight_id","passenger_id","connection_flight_id","inbound_flight_id","transfer_flight_id","direction"}} for row in p[fields[kind]]]
  print(json.dumps({"kind":kind,"event_id":d["event_id"],"batch":p["seed_batch_id"],"topic":m.topic(),"partition":m.partition(),"offset":m.offset(),"rows":rows}),flush=True)
'''
    file = facts_path.open("w")
    process = subprocess.Popen(["docker", "exec", f"{PROJECT}-sim-orchestrator-1", "python", "-u", "-c", code, day],
                               stdout=file, stderr=(OUT / "observer-errors.txt").open("w"))
    def assigned():
        assert process.poll() is None, "Kafka observer exited"
        assert facts_path.exists() and '"observer_ready": true' in facts_path.read_text(), "waiting for Kafka audit assignment"
    wait(assigned, 60)
    return process


def main():
    global observer
    save("initial_readiness", wait(ready))
    token = requests.post("http://localhost:3000/auth/token", json={"client_id":"dashboard","secret":"art-dev-secret"}, timeout=10)
    token.raise_for_status()
    http.headers["Authorization"] = "Bearer " + token.json()["token"]
    call("/api/v1/sim/pause", "POST")
    initial = status()
    assert initial["day_number"] >= 47, "Original airport must not rewind"
    save("restored_clock", {k:initial[k] for k in ("sim_time","day_number","paused","speed_multiplier")})
    verify_builds("deployed-builds-before.json")
    disposition = call("/api/v1/baggage/legacy-summary")
    before = json.loads((OUT / "legacy-before.json").read_text())
    expected = sum(row["missing_id"] for row in before["bags"]) + before["bag_archives"][0]["n"]
    assert disposition["migration"]["linked"] + disposition["migration"]["quarantined"] == expected
    assert disposition["retained_quarantine"] == disposition["migration"]["quarantined"]
    assert query("MATCH(b:LegacyBaggage) RETURN count(b.passenger_id) AS invented")[0]["invented"] == 0
    assert query("MATCH(b:Baggage) WHERE b.passenger_id IS NULL RETURN count(b) AS n")[0]["n"] == 0
    save("legacy_disposition", disposition)

    # A harmless, unimported shared file tests detection without altering domain data.
    container = f"{PROJECT}-passenger-service-1"
    path = "/app/_common/rc14_integrity_probe.py"
    subprocess.run(["docker","exec",container,"python","-c",f"from pathlib import Path; p=Path({path!r}); assert not p.exists(); p.write_text('# RC14 stale overlay probe\\n')"],check=True)
    try:
        owner = requests.get("http://localhost:8002/build",timeout=5).json()
        assert owner["integrity"] is False
        assert requests.get("http://localhost:8002/ready",timeout=10).status_code == 503
        assert requests.get("http://localhost:3000/ready",timeout=15).status_code == 503
        save("stale_shared_overlay_rejected", owner["errors"])
    finally:
        subprocess.run(["docker","exec",container,"python","-c",f"from pathlib import Path; Path({path!r}).unlink()"],check=True)
    raw = subprocess.check_output(["docker","exec",container,"cat","/app/build-identity.json"])
    old = json.loads(raw)
    old["revision"] = "16f14dcbcb3b7b5ee3025b01040b15f80857c812"
    write = ["docker","exec","-i",container,"python","-c","import sys; from pathlib import Path; Path('/app/build-identity.json').write_bytes(sys.stdin.buffer.read())"]
    subprocess.run(write,input=json.dumps(old).encode(),check=True)
    try:
        assert requests.get("http://localhost:3000/ready",timeout=15).status_code == 503
        save("mixed_revision_rejected", True)
    finally:
        subprocess.run(write,input=raw,check=True)
    gateway = f"{PROJECT}-api-gateway-1"
    policy_path = "/app/dist/wsDeliveryPolicy.json"
    policy = subprocess.check_output(["docker","exec",gateway,"cat",policy_path])
    changed_policy = json.loads(policy)
    changed_policy["_rc14_integrity_probe"] = True
    write_policy = ["docker","exec","-i",gateway,"node","-e","const fs=require('fs');fs.writeFileSync('/app/dist/wsDeliveryPolicy.json',fs.readFileSync(0));"]
    subprocess.run(write_policy,input=json.dumps(changed_policy).encode(),check=True)
    try:
        identity = requests.get("http://localhost:3000/build",timeout=5).json()
        assert identity["integrity"] is False
        assert requests.get("http://localhost:3000/ready",timeout=15).status_code == 503
        save("compiled_json_policy_rejected",identity["errors"])
    finally:
        subprocess.run(write_policy,input=policy,check=True)
    wait(ready)
    day = (sim_time().date() + timedelta(days=1)).isoformat()
    observer = start_observer(day)
    call("/api/v1/sim/settings","PATCH",{"daily_flights":60})
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":60})
    call("/api/v1/sim/resume","POST")
    wait(owner_aligned)
    outage_start = sim_time()
    compose("stop","passenger-service","baggage-service")
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":3600})
    target = outage_start + timedelta(hours=6)
    def outage_elapsed():
        now = sim_time()
        assert now >= target, f"outage clock {now.isoformat()} < {target.isoformat()}"
        return now.isoformat()
    save("six_hour_outage", {"start":outage_start.isoformat(),"end":wait(outage_elapsed)})
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":60})
    recovery_start = time.monotonic()
    compose("start","passenger-service","baggage-service")
    recovered = wait(owner_aligned)
    save("moving_clock_recovery", {"elapsed_seconds":round(time.monotonic()-recovery_start,2),
                                  "sim_time":recovered["sim_time"],"watermarks":recovered["watermarks"]})
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":3600})
    target = datetime.fromisoformat(day+"T18:00:00")
    def daytime():
        now = sim_time()
        assert now >= target, f"daytime clock {now.isoformat()} < {target.isoformat()}"
        return now.isoformat()
    wait(daytime)
    call("/api/v1/sim/pause","POST")
    frozen = sim_time()
    def drained():
        marks=query("MATCH(s) WHERE s:FlightRuntime OR s:PassengerRuntime OR s:BaggageOutboxSeq RETURN s.last_tick_sim_time AS at")
        assert len(marks)==3 and all(r["at"] and datetime.fromisoformat(r["at"]).replace(tzinfo=None)>=frozen for r in marks), marks
    wait(drained)
    facts = [json.loads(line) for line in facts_path.read_text().splitlines() if line.strip()]
    flight_ids = sorted({r["id"] for f in facts if f.get("kind")=="FlightsScheduled" for r in f["rows"]})
    pax_ids = sorted({r["id"] for f in facts if f.get("kind")=="PassengersSeeded" for r in f["rows"]})
    bag_ids = sorted({r["id"] for f in facts if f.get("kind")=="BaggageSeeded" for r in f["rows"]})
    assert len(flight_ids)==60 and pax_ids and bag_ids, (len(flight_ids),len(pax_ids),len(bag_ids))
    seed = query("MATCH(d:SeedDay {id:$day}) RETURN d.ready AS ready",day=day)
    assert seed and seed[0]["ready"]
    assert query("MATCH(b:SeedBatch {pending:true}) RETURN count(b) AS n")[0]["n"]==0
    links=query("UNWIND $ids AS id MATCH(b) WHERE (b:Baggage OR b:BaggageArchive) AND b.id=id RETURN count(b) AS n, sum(CASE WHEN b.passenger_id IS NOT NULL AND EXISTS { (p)-[:CARRIES]->(b) WHERE p.id=b.passenger_id } THEN 0 ELSE 1 END) AS invalid",ids=bag_ids)[0]
    assert links=={"n":len(bag_ids),"invalid":0},links
    early=query("UNWIND $ids AS id MATCH(p) WHERE (p:Passenger OR p:PassengerArchive) AND p.id=id AND p.baggage_claim_at IS NOT NULL AND p.departed_airport_at IS NOT NULL WITH p, duration.inSeconds(datetime(p.baggage_claim_at),datetime(p.departed_airport_at)).seconds AS elapsed RETURN count(p) AS exits, sum(CASE WHEN elapsed>=0 AND elapsed<2700 THEN 1 ELSE 0 END) AS early",ids=pax_ids)[0]
    assert early["early"]>0, early
    transfers=query("UNWIND $ids AS id MATCH(p) WHERE (p:Passenger OR p:PassengerArchive) AND p.id=id AND p.inbound_flight_id IS NOT NULL RETURN count(p) AS n",ids=pax_ids)[0]["n"]
    transfer_bags=query("UNWIND $ids AS id MATCH(b) WHERE (b:Baggage OR b:BaggageArchive) AND b.id=id AND b.inbound_flight_id IS NOT NULL RETURN count(b) AS n",ids=bag_ids)[0]["n"]
    assert transfers>0 and transfer_bags>0
    phantom=query("MATCH(p:Passenger {status:'airborne'})-[:ON_FLIGHT]->(f:Flight {direction:'arrival',status:'scheduled'}) RETURN count(p) AS n")[0]["n"]
    assert phantom==0
    save("arrival_transfer_day_boundary", {"day":day,"clock":frozen.isoformat(),"flights":len(flight_ids),"passengers":len(pax_ids),"bags":len(bag_ids),"links":links,"claim_exits":early,"transfers":transfers,"transfer_bags":transfer_bags,"phantom_airborne":phantom,
       "owner_seed_facts":[{k:v for k,v in f.items() if k!="rows"} for f in facts if "kind" in f]})
    observed=query("UNWIND $ids AS id MATCH(o:PassengerBaggageObservation {id:id}) RETURN count(o) AS n,count(o.collected_at) AS collected",ids=pax_ids)[0]
    assert observed["collected"]>0
    compose("restart","passenger-service","baggage-service","sim-orchestrator","api-gateway")
    wait(ready)
    assert status()["paused"] and sim_time()==frozen
    assert query("UNWIND $ids AS id MATCH(o:PassengerBaggageObservation {id:id}) RETURN count(o) AS n,count(o.collected_at) AS collected",ids=pax_ids)[0]==observed
    save("durable_collection_restart", observed)
    verify_builds("deployed-builds-final.json")
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":60})
    call("/api/v1/sim/resume","POST")
    save("final_readiness",wait(ready))
    save("passed",True)


def resume_restart():
    global report
    report = json.loads((OUT / "live-validation.json").read_text())
    assert "arrival_transfer_day_boundary" in report and report.get("passed") is not True
    frozen = datetime.fromisoformat(report["arrival_transfer_day_boundary"]["clock"])
    assert status()["paused"] and sim_time() == frozen
    facts = [json.loads(line) for line in facts_path.read_text().splitlines() if line.strip()]
    pax_ids = sorted({r["id"] for f in facts if f.get("kind") == "PassengersSeeded" for r in f["rows"]})
    observed = query("UNWIND $ids AS id MATCH(o:PassengerBaggageObservation {id:id}) RETURN count(o) AS n,count(o.collected_at) AS collected",ids=pax_ids)[0]
    assert observed["collected"] > 0, observed
    report.pop("error",None)
    save("projection_lookup_correction", "PassengerBaggageObservation.id is a passenger ID; use the observed owner passenger cohort, not bag IDs.")
    compose("restart","passenger-service","baggage-service","sim-orchestrator","api-gateway")
    wait(ready)
    assert status()["paused"] and sim_time() == frozen
    assert query("UNWIND $ids AS id MATCH(o:PassengerBaggageObservation {id:id}) RETURN count(o) AS n,count(o.collected_at) AS collected",ids=pax_ids)[0] == observed
    save("durable_collection_restart",observed)
    verify_builds("deployed-builds-final.json")
    token = requests.post("http://localhost:3000/auth/token",json={"client_id":"dashboard","secret":"art-dev-secret"},timeout=10)
    token.raise_for_status()
    http.headers["Authorization"] = "Bearer " + token.json()["token"]
    call("/api/v1/sim/speed","PATCH",{"speed_multiplier":60})
    call("/api/v1/sim/resume","POST")
    save("final_readiness",wait(ready))
    save("passed",True)


if __name__ == "__main__":
    try:
        if "--resume-restart" in sys.argv:
            resume_restart()
        else:
            main()
    except Exception as error:
        save("error",str(error))
        try:
            call("/api/v1/sim/pause","POST")
        except requests.RequestException:
            pass
        raise
    finally:
        if observer is not None:
            if observer.poll() is None and facts_path.exists():
                header = json.loads(facts_path.read_text().splitlines()[0])
                pid = header.get("pid")
                if isinstance(pid, int) and pid > 1:
                    cleanup = "import os,signal; from pathlib import Path; p=" + str(pid) + "; f=Path('/proc')/str(p)/'cmdline'; c=f.read_bytes() if f.exists() else b''; os.kill(p,signal.SIGTERM) if b'rc14-audit-' in c else None"
                    subprocess.run(["docker","exec",f"{PROJECT}-sim-orchestrator-1","python","-c",cleanup],check=False)
            observer.terminate()
        driver.close()

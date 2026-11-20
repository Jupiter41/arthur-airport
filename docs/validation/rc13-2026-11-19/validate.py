"""RC13 live closure probe. Run against a fresh, unused RC13_PROJECT compose project.

Uses only public owner/gateway controls and read-only graph assertions. Never
rewrites graph state or bypasses startup/restart paths. Preserves all volumes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from neo4j import GraphDatabase
import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROJECT = os.getenv("RC13_PROJECT", "art-rc13-verified")
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "docker-compose.yml"),
           "-f", str(OUT / "compose.override.yml")]
http = requests.Session()


def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    response = http.request(method, f"http://localhost:3000{path}", json=body, timeout=10)
    response.raise_for_status()
    return response.json()


def wait(check, seconds: int = 120):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            return check()
        except (requests.RequestException, AssertionError) as error:
            last = error
            time.sleep(1)
    raise AssertionError(f"Timed out: {last}")


def snapshot(name: str) -> dict:
    value = call("/api/v1/sim/settings")
    (OUT / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def available() -> dict:
    value = call("/api/v1/sim/settings")
    assert all(value["effective"][owner]["status"] == "available" for owner in ("passenger", "baggage"))
    return value


def compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], cwd=ROOT, check=True)


def main() -> None:
    token = requests.post("http://localhost:3000/auth/token", json={
        "client_id": "dashboard", "secret": "art-dev-secret",
    }, timeout=10)
    token.raise_for_status()
    http.headers["Authorization"] = f"Bearer {token.json()['token']}"
    wait(available)
    call("/api/v1/sim/pause", "POST")
    assert call("/api/v1/sim/status")["day_number"] == 1, "Probe requires an unused cold-start project"
    initial = snapshot("cold-start")
    assert [initial[f"lanes_{t}"] for t in "abc"] == [8, 12, 8]
    assert initial["sorting_capacity"] == 5400
    assert initial["screening_units"] == 6
    assert initial["effective"]["passenger"]["values"] == {
        "lanes_a": 8, "lanes_b": 12, "lanes_c": 8, "mct_minutes": 45,
    }
    assert initial["effective"]["baggage"]["values"]["sorting_capacity"] == 5400
    print("PASS cold startup: configured and owner-observed lanes 8/12/8; sorting 5400/h", flush=True)

    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "art-digital-twin"))
    def query(cypher: str, **parameters):
        return driver.execute_query(cypher, parameters_=parameters).records
    day_one = query("MATCH (f:Flight) WHERE f.scheduled_time STARTS WITH '2024-06-15' RETURN count(f) AS flights")[0]["flights"]
    assert day_one == 60
    saved = call("/api/v1/sim/settings", "PATCH", {
        "daily_flights": 80, "lanes_a": 4, "lanes_b": 3, "lanes_c": 4,
        "sorting_capacity": 1800, "wind_kt": 90,
    })
    assert saved["requested"]["daily_flights"] == 80
    assert saved["application"]["wind_kt"] == "stored_only"
    requested = snapshot("saved-preferences")
    assert requested["effective"]["passenger"]["values"] == initial["effective"]["passenger"]["values"]
    assert requested["effective"]["baggage"]["values"] == initial["effective"]["baggage"]["values"]

    command_id = "rc13-live-lanes-A"
    receipt = call("/api/v1/passengers/flow/security/A/lanes", "POST", {"lanes_open": 3, "command_id": command_id})
    assert receipt["event_type"] == "CommandExecuted" and receipt["applied"]
    replay = call("/api/v1/passengers/flow/security/A/lanes", "POST", {"lanes_open": 9, "command_id": command_id})
    assert not replay["applied"] and replay["receipt"] == receipt["receipt"]
    applied = snapshot("owner-applied")
    assert applied["requested"]["lanes_a"] == 4
    assert applied["effective"]["passenger"]["values"]["lanes_a"] == 3
    assert query("MATCH (r:CommandReceipt {id: $id}) RETURN r.event_type AS kind", id=command_id)[0]["kind"] == "CommandExecuted"
    (OUT / "lane-receipts.json").write_text(json.dumps({"command": receipt, "replay": replay}, indent=2) + "\n")
    print("PASS explicit owner application and stable-ID replay: observed lanes A=3, saved request A=4", flush=True)

    before = call("/api/v1/sim/status")
    compose("restart", "sim-orchestrator", "passenger-service", "baggage-service", "api-gateway")
    wait(available)
    restored = snapshot("durable-restart")
    assert restored["requested"] == applied["requested"]
    assert restored["effective"]["passenger"]["values"] == applied["effective"]["passenger"]["values"]
    assert restored["effective"]["baggage"]["values"] == applied["effective"]["baggage"]["values"]
    after = call("/api/v1/sim/status")
    assert after["paused"] and after["sim_time"] == before["sim_time"]
    print("PASS durable restart: stale preferences remain requested; owner lane override survives", flush=True)

    compose("stop", "baggage-service")
    def unavailable():
        result = call("/api/v1/sim/settings")
        assert result["effective"]["baggage"]["status"] == "unavailable"
        assert result["effective"]["baggage"]["values"] is None
        return result
    wait(unavailable)
    snapshot("owner-unavailable")
    compose("start", "baggage-service")
    wait(available)
    print("PASS owner outage: effective capacity unknown, saved 1800 never substituted", flush=True)

    call("/api/v1/sim/speed", "PATCH", {"speed_multiplier": 3600})
    call("/api/v1/sim/resume", "POST")
    def next_day():
        rows = query("MATCH (f:Flight) WHERE f.scheduled_time STARTS WITH '2024-06-16' RETURN count(f) AS flights")
        assert rows[0]["flights"] == 80
        return rows[0]["flights"]
    next_count = wait(next_day, seconds=600)
    call("/api/v1/sim/pause", "POST")
    assert query("MATCH (f:Flight) WHERE f.scheduled_time STARTS WITH '2024-06-15' RETURN count(f) AS flights")[0]["flights"] == day_one
    (OUT / "manifest-application.json").write_text(json.dumps({
        "initial_daily_request": 60, "saved_future_request": 80,
        "existing_day_flights_after_change": day_one, "next_day_owner_flights": next_count,
        "sim_status": call("/api/v1/sim/status"),
    }, indent=2) + "\n")
    print("PASS future manifest application: day one remains 60 flights; next day owner has 80", flush=True)
    driver.close()

    fingerprints = {}
    paths = {
        "sim-orchestrator": ["services/settings.py", "routers/sim.py"],
        "passenger-service": ["routers/passengers.py"],
        "baggage-service": ["routers/baggage.py"],
        "api-gateway": ["dist/settings.js", "dist/index.js"],
        "dashboard": ["/usr/share/nginx/html/index.html"],
    }
    for service, files in paths.items():
        container = f"{PROJECT}-{service}-1"
        image = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]["Image"]
        hashes = {}
        for file in files:
            content = subprocess.check_output(["docker", "exec", container, "cat", file])
            digest = hashlib.sha256(content).hexdigest()
            hashes[file] = digest
            local = ROOT / "services" / service / file
            if service == "api-gateway":
                local = Path("/tmp/rc13-gateway-dist") / Path(file).name
            if service != "dashboard":
                assert local.is_file(), f"Compile the gateway first: {local}"
                assert digest == hashlib.sha256(local.read_bytes()).hexdigest(), (service, file)
        fingerprints[service] = {"image": image, "sha256": hashes}
    (OUT / "image-fingerprints.json").write_text(json.dumps(fingerprints, indent=2) + "\n")
    print("PASS image/source fingerprints for all changed Python owners; built gateway and dashboard recorded", flush=True)


if __name__ == "__main__":
    main()

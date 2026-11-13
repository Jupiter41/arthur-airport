"""Bounded checks against this project's deployed airport; never prints tokens."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="https://airportdt.duckdns.org")
args = parser.parse_args()
base = args.base.rstrip("/")
if base != "https://airportdt.duckdns.org":
    raise SystemExit("This script is scoped to https://airportdt.duckdns.org")


def request(path: str, method: str = "GET", token: str | None = None,
            body: dict | None = None, lease: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if lease:
        headers["X-Control-Lease"] = lease
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def expect(label: str, actual: int, expected: int) -> None:
    assert actual == expected, f"{label}: {actual}, expected {expected}"
    print(f"PASS {label}: {actual}", flush=True)


env = dict(line.split("=", 1) for line in Path("/opt/arthur-airport/.env.pi").read_text().splitlines() if "=" in line)
clients = json.loads(env["AUTH_CLIENTS"])
client_id = next(iter(clients))
credentials = {"client_id": client_id, "secret": clients[client_id]["secret"]}
status, viewer = request("/auth/viewer", "POST", body={})
expect("public viewer issuance", status, 200)
v = viewer["token"]
expect("anonymous API denied", request("/api/v1/sim/status")[0], 401)
expect("viewer write denied", request("/api/v1/sim/pause", "POST", v)[0], 403)
expect("forged JWT denied", request("/api/v1/sim/status", token="forged.jwt.token")[0], 401)
status, first = request("/auth/token", "POST", body=credentials)
expect("operator login", status, 200)
status, second = request("/auth/token", "POST", body=credentials)
expect("second operator session", status, 200)
a, b = first["token"], second["token"]
expect("development credentials rejected", request("/auth/token", "POST", body={"client_id": "dashboard", "secret": "art-dev-secret"})[0], 401)
expect("operator requires control", request("/api/v1/sim/settings", "PATCH", a, {"wind_kt": 15})[0], 423)
status, ownership = request("/api/v1/control", "POST", a)
expect("acquire controller", status, 200)
lease = ownership["lease"]
try:
    expect("second session cannot acquire", request("/api/v1/control", "POST", b)[0], 409)
    expect("second session cannot use stolen lease", request("/api/v1/sim/settings", "PATCH", b, {"wind_kt": 15}, lease)[0], 423)
    for path in ("/api/v1/debug/cypher", "/api/v1/sim/reset", "/api/v1/analysis/training/start", "/api/v1/analysis/query", "/api/v1/planning/scenarios"):
        expect("admin endpoint " + path, request(path, "POST", a, {}, lease)[0], 403)
    expect("excessive speed denied", request("/api/v1/sim/speed", "PATCH", a, {"speed_multiplier": 3600}, lease)[0], 400)
    expect("excessive flights denied", request("/api/v1/sim/settings", "PATCH", a, {"daily_flights": 5000}, lease)[0], 400)
    expect("unbounded query denied", request("/api/v1/flights?limit=100000", token=v)[0], 400)
    # Same-value settings commands exercise the real HTTP path without changing
    # the airport configuration chosen by its operator.
    status, settings = request("/api/v1/sim/settings", token=a)
    expect("read settings", status, 200)
    payload = {"wind_kt": settings.get("wind_kt", 15)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = list(pool.map(lambda _: request("/api/v1/sim/settings", "PATCH", a, payload, lease)[0], range(2)))
    assert sorted(writes) == [200, 409], f"overlapping writes: {writes}"
    print("PASS overlapping writes: one success, one explicit conflict", flush=True)
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: request("/api/v1/flights?limit=50", token=v)[0], range(8)))
    assert all(code == 200 for code in results), results
    print(f"PASS 8 concurrent viewers: {time.monotonic() - start:.2f}s", flush=True)
finally:
    expect("release controller", request("/api/v1/control", "DELETE", a, lease=lease)[0], 200)
status, snapshot = request("/api/v1/airport", token=v)
expect("airport snapshot", status, 200)
print("Degraded services:", snapshot.get("degraded_services", []))

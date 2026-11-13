"""Host-only setup/restart verification via the authenticated gateway."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["pause", "resume", "verify"])
args = parser.parse_args()
root = Path("/opt/arthur-airport")
env = dict(line.split("=", 1) for line in (root / ".env.pi").read_text().splitlines() if "=" in line)
clients = json.loads(env["AUTH_CLIENTS"])
client_id = next(iter(clients))
base = "https://airportdt.duckdns.org"


def call(path, method="GET", body=None, token=None, lease=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    if lease: headers["X-Control-Lease"] = lease
    request = urllib.request.Request(base + path, method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


token = call("/auth/token", "POST", {"client_id": client_id, "secret": clients[client_id]["secret"]})["token"]
if args.action == "verify":
    before = json.loads((root / "restart-before.json").read_text())
    after = call("/api/v1/sim/status", token=token)
    assert after["paused"] is True
    assert after["speed_multiplier"] == 1
    assert after["tick_number"] == before["tick_number"]
    assert datetime.fromisoformat(after["sim_time"]) == datetime.fromisoformat(before["sim_time"])
    print("PASS restart preserved clock, tick, speed, and pause state")
else:
    lease = call("/api/v1/control", "POST", token=token)["lease"]
    try:
        if args.action == "pause":
            call("/api/v1/sim/speed", "PATCH", {"speed_multiplier": 1}, token, lease)
        call("/api/v1/sim/" + args.action, "POST", token=token, lease=lease)
        status = call("/api/v1/sim/status", token=token)
        if args.action == "pause":
            (root / "restart-before.json").write_text(json.dumps(status))
        print(json.dumps({k: status.get(k) for k in ("paused", "speed_multiplier", "sim_time", "tick_number")}))
    finally:
        call("/api/v1/control", "DELETE", token=token, lease=lease)

"""Restore original operator demand/speed after a successful rollout audit."""
from pathlib import Path
import json
import time

import requests

OUT = Path(__file__).resolve().parent
http = requests.Session()
for attempt in range(1800):
    value = json.loads((OUT / "live-validation.json").read_text())
    if value.get("error"):
        raise RuntimeError("Audit failed; leave the clock paused for diagnosis")
    if value.get("passed"):
        break
    time.sleep(1)
else:
    raise RuntimeError("Audit did not finish within the restoration budget")

baseline = json.loads((OUT / "legacy-before.json").read_text())["clock"][0]["state"]
original = json.loads(baseline["settings_json"])
token = http.post("http://localhost:3000/auth/token", json={"client_id":"dashboard","secret":"art-dev-secret"}, timeout=10)
token.raise_for_status()
http.headers["Authorization"] = "Bearer " + token.json()["token"]
for method, path, body in [
    ("PATCH", "/sim/settings", {"daily_flights": original["daily_flights"]}),
    ("PATCH", "/sim/speed", {"speed_multiplier": baseline["speed_multiplier"]}),
    ("POST", "/sim/pause" if baseline["paused"] else "/sim/resume", None),
]:
    response = http.request(method, "http://localhost:3000/api/v1" + path, json=body, timeout=15)
    response.raise_for_status()
settings = http.get("http://localhost:3000/api/v1/sim/settings", timeout=15).json()
status = http.get("http://localhost:3000/api/v1/sim/status", timeout=15).json()
assert settings["daily_flights"] == original["daily_flights"]
assert status["speed_multiplier"] == baseline["speed_multiplier"] and status["paused"] == baseline["paused"]
report = {"daily_flights":settings["daily_flights"],"speed_multiplier":status["speed_multiplier"],
          "paused":status["paused"],"sim_time":status["sim_time"]}
(OUT / "profile-restored.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))

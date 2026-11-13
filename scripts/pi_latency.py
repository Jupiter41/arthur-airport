"""Small read-only latency sample against the public airport."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
import urllib.request

BASE = "https://airportdt.duckdns.org"
with urllib.request.urlopen(urllib.request.Request(BASE + "/auth/viewer", method="POST"), timeout=30) as response:
    token = json.load(response)["token"]


def measure(path: str):
    start = time.monotonic()
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    return round((time.monotonic() - start) * 1000, 1), payload


for path in ("/api/v1/sim/status", "/api/v1/flights?limit=50", "/api/v1/passengers/flow/summary"):
    first, _ = measure(path)
    second, _ = measure(path)
    print(path, "first_ms=", first, "cached_ms=", second, flush=True)
with ThreadPoolExecutor(max_workers=8) as pool:
    times = list(pool.map(lambda _: measure("/api/v1/flights?limit=50")[0], range(8)))
print("8 simultaneous reads (ms):", times, flush=True)
_, status = measure("/api/v1/sim/status")
print("Clock:", {k: status.get(k) for k in ("sim_time", "tick_number", "speed_multiplier", "paused")})

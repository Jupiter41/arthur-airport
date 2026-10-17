"""Fail-closed validation of every service, then the live integration suite.

Run against a disposable Compose stack; integration tests inject fake incidents
and restart services. Requires requests + pytest and the service test packages.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests

SERVICES = {
    "flight": ("FLIGHT_SVC_URL", 8001),
    "passenger": ("PASSENGER_SVC_URL", 8002),
    "baggage": ("BAGGAGE_SVC_URL", 8003),
    "weather": ("WEATHER_SVC_URL", 8004),
    "incident": ("INCIDENT_SVC_URL", 8005),
    "sim": ("SIM_SVC_URL", 8006),
    "analysis": ("ANALYSIS_SVC_URL", 8007),
    "cost": ("COST_SVC_URL", 8008),
    "planning": ("PLANNING_SVC_URL", 8009),
    "gateway": ("GATEWAY_URL", 3000),
}
ROOT = Path(__file__).resolve().parents[1]


def readiness() -> dict[str, dict]:
    def check(item):
        name, (env, port) = item
        url = os.getenv(env, f"http://localhost:{port}").rstrip("/") + "/ready"
        try:
            response = requests.get(url, timeout=5)
            return name, {"ready": response.status_code == 200, "status": response.status_code}
        except requests.RequestException as exc:
            return name, {"ready": False, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        return dict(pool.map(check, SERVICES.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--readiness-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    while True:
        result = readiness()
        if all(row["ready"] for row in result.values()):
            break
        if time.monotonic() >= deadline:
            print(json.dumps({"ready": False, "services": result}, indent=2))
            if args.report:
                args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return 1
        time.sleep(2)
    print(json.dumps({"ready": True, "services": result}, indent=2))
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.readiness_only:
        return 0
    env = {**os.environ, "REQUIRE_LIVE_STACK": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration", "-q", "--tb=short"],
        cwd=ROOT, env=env, check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())

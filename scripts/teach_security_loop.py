#!/usr/bin/env python3
"""Run a real security-lane decision through a disposable local gateway.

Credentials: ART_CLIENT_ID / ART_CLIENT_SECRET (approver), or ART_API_TOKEN.
The runner never invents execution receipts or outcomes and never resets data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class Gateway:
    def __init__(self, base: str, token: str | None = None) -> None:
        self.base, self.token = base.rstrip("/"), token

    def request(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"Gateway {method} {path}: {exc.code} {detail}") from exc

    def api(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        return self.request("/api/v1" + path, method, body)


def wait_for(read: Callable[[], object], timeout: float, description: str) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read()
        if result:
            return result
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}; no success evidence was manufactured")


def choose_flights(flights: list[dict], now: str) -> dict[str, str]:
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    chosen = {}
    for flight in flights:
        gate = flight.get("gate_id") or ""
        terminal = gate[:1]
        scheduled = flight.get("scheduled_time") or flight.get("scheduled_departure")
        if terminal not in {"A", "B", "C"} or flight.get("direction", flight.get("flight_type")) != "departure" or not scheduled:
            continue
        departure = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if departure.tzinfo is None:
            departure = departure.replace(tzinfo=timezone.utc)
        # Keep injected passengers' flights away from boarding during measurement.
        if (departure - current).total_seconds() >= 90 * 60:
            chosen.setdefault(terminal, flight["id"])
    if set(chosen) != {"A", "B", "C"}:
        raise ValueError("Need a synthetic departure with a gate in each terminal, at least 90 sim-minutes ahead")
    return chosen


def run_lesson(gateway: Gateway, output: Path, timeout: float) -> dict:
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    if gateway.api("/control").get("enabled"):
        raise ValueError("Teaching injection is disabled on public deployments; use a disposable local stack")
    sim = gateway.api("/sim/status")
    if not sim.get("sim_time"):
        raise ValueError("The simulation must have received its first clock tick")
    settings = gateway.api("/sim/settings")
    autonomous = gateway.api("/analysis/autonomous")["autonomous"]
    original_security = gateway.api("/passengers/flow/summary")["security"]
    original_lanes = {terminal: (original_security.get(terminal) or original_security.get(f"Terminal {terminal}") or original_security[f"terminal_{terminal.lower()}"])["lanes_open"] for terminal in ("A", "B", "C")}
    patch = {"weather_lock": "CAVOK",
             "runway_incursion_rate": 0, "baggage_fire_rate": 0, "security_breach_rate": 0, "system_failure_rate": 0}
    existing = {p["id"] for p in gateway.api("/analysis/approvals?all=true")["approvals"]}
    if any(p["status"] in {"pending", "approved", "dispatched"} for p in gateway.api("/analysis/approvals?all=true")["approvals"]):
        raise ValueError("Finish existing proposals first so the teaching controls remain untreated")
    result = None
    restore_errors = []
    try:
        gateway.api("/analysis/autonomous", "PATCH", {**autonomous, "enabled": False})
        gateway.api("/sim/pause", "POST", {})
        gateway.api("/sim/settings", "PATCH", patch)
        setup_receipts = {}
        for terminal, lanes in (("A", 1), ("B", 4), ("C", 4)):
            setup_receipts[terminal] = gateway.api(f"/passengers/flow/security/{terminal}/lanes", "POST", {"lanes_open": lanes})
        try:
            flights = choose_flights(gateway.api("/flights?limit=500")["flights"], sim["sim_time"])
        except ValueError:
            # Most future departures have no gate yet. Seed three explicit lab
            # flights through the existing synthetic-injection API instead.
            gates = gateway.api("/gates")["gates"]
            departure = (datetime.fromisoformat(sim["sim_time"].replace("Z", "+00:00")) + timedelta(hours=3)).isoformat()
            flights = {}
            for terminal in ("A", "B", "C"):
                gate = next((g.get("gate_id", g.get("id")) for g in gates
                             if str(g.get("gate_id", g.get("id", ""))).startswith(terminal)
                             and not g.get("flight_id") and g.get("status") not in {"closed", "maintenance", "offline"}), None)
                if not gate:
                    raise ValueError(f"No available gate for teaching Terminal {terminal}")
                seeded = gateway.api("/debug/inject/flight", "POST", {"direction": "departure", "gate": gate,
                    "departure_time": departure, "seed_passengers": False, "seed_baggage": False})
                flights[terminal] = seeded["flight_id"]
        # Counts and terminals are controlled; all generated personal data is fake.
        for terminal, count in (("A", 450), ("B", 180), ("C", 180)):
            gateway.api("/debug/inject/passengers", "POST", {"flight_id": flights[terminal], "count": count, "status": "security_queue"})
        gateway.api("/sim/speed", "PATCH", {"speed_multiplier": 60})
        gateway.api("/sim/resume", "POST", {})

        def recommendation():
            rows = gateway.api("/analysis/recommendations")["recommendations"]
            return next((r for r in rows if r["action_type"] == "open_security_lane" and
                         r["parameters"].get("terminal") in {"A", "Terminal A"} and r.get("executable")
                         and r["parameters"].get("new_lane_count") == 2), None)
        rec = wait_for(recommendation, timeout, "Terminal A's executable recommendation")
        submitted = gateway.api(f"/analysis/recommendations/{quote(rec['id'], safe='')}/apply", "POST", {"request_approval": True})
        proposal_id = submitted["proposal_id"]
        gateway.api(f"/analysis/approvals/{quote(proposal_id, safe='')}/approve", "POST", {"decided_by": "teaching-operator"})

        def measured():
            decision = gateway.api(f"/analysis/decisions/{quote(proposal_id, safe='')}")
            if decision["status"] in {"failed", "rejected"}:
                raise RuntimeError(f"Teaching action failed: {decision.get('failure_reason')}")
            return decision if decision["status"] == "measured" else None
        decision = wait_for(measured, timeout, "owner execution and simulation-clock outcome")
        receipt = decision.get("receipt") or {}
        if receipt.get("event_type") != "CommandExecuted" or receipt.get("topic") != "passengers.events":
            raise RuntimeError("The measured decision has no passenger-owner execution receipt")
        proposals = gateway.api("/analysis/approvals?all=true")["approvals"]
        contaminated = [p["id"] for p in proposals if p["id"] not in existing | {proposal_id}
                        and p.get("parameters", {}).get("terminal") in {"B", "C", "Terminal B", "Terminal C"}]
        result = {"scenario": "security-lane-teaching-v1", "data_source": "live_synthetic_stack",
                  "injected_counts": {"A": 450, "B": 180, "C": 180}, "flights": flights,
                  "setup_owner_receipts": setup_receipts,
                  "control_interventions_detected": contaminated, "empirical_accuracy": "unvalidated",
                  "decision": decision, "note": "One observational example; no randomized causal claim."}
        attribution = (decision.get("outcome") or {}).get("attribution") or {}
        if not decision.get("predicted") or not attribution.get("calibration_eligible") or attribution.get("control_count", 0) < 2:
            result["verification_status"] = "incomplete_attribution"
            raise RuntimeError("Outcome recorded without an eligible prediction and two fresh untreated controls; see exported evidence")
        if contaminated:
            raise RuntimeError("Comparison terminals received other interventions; run is contaminated")
        result["verification_status"] = "complete_observational_example"
    finally:
        restore = [(f"/passengers/flow/security/{terminal}/lanes", "POST", {"lanes_open": lanes})
                   for terminal, lanes in original_lanes.items()]
        restore.extend((
            ("/sim/settings", "PATCH", {k: settings[k] for k in patch}),
            ("/analysis/autonomous", "PATCH", autonomous),
            ("/sim/speed", "PATCH", {"speed_multiplier": sim["speed_multiplier"]}),
            ("/sim/pause" if sim.get("paused") else "/sim/resume", "POST", {}),
        ))
        for path, method, body in restore:
            try:
                gateway.api(path, method, body)
            except Exception as exc:
                restore_errors.append(str(exc))
        if result is not None:
            result["restoration_errors"] = restore_errors
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if restore_errors:
            raise RuntimeError("Lab settings could not be fully restored: " + "; ".join(restore_errors))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://localhost:3000")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if urlparse(args.gateway).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use a disposable local gateway, never a remote/public airport")
    gateway = Gateway(args.gateway, os.getenv("ART_API_TOKEN"))
    if not gateway.token:
        client, secret = os.getenv("ART_CLIENT_ID"), os.getenv("ART_CLIENT_SECRET")
        if not client or not secret:
            parser.error("Set ART_CLIENT_ID and ART_CLIENT_SECRET for an approver account, or ART_API_TOKEN")
        gateway.token = gateway.request("/auth/token", "POST", {"client_id": client, "secret": secret})["token"]
    result = run_lesson(gateway, args.output, args.timeout)
    print(f"Recorded actual decision {result['decision']['id']} in {args.output}")


if __name__ == "__main__":
    main()

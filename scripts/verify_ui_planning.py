"""Exercise a synthetic isolated experiment through a local gateway.

Leaves the named scenario/results as durable review evidence. Never resets or
mutates the shared airport. Credentials are read from the environment and are
never written to the evidence file.
"""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://localhost:3002")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-existing", action="store_true",
                        help="Reread the saved evidence's scenario without creating a job")
    args = parser.parse_args()
    headers = {"Content-Type": "application/json"}

    def request(path: str, body: dict | None = None) -> dict:
        req = Request(args.gateway.rstrip("/") + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers=headers)
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    login = request("/auth/token", {
        "client_id": os.getenv("UI_VERIFY_CLIENT", "dashboard"),
        "secret": os.getenv("UI_VERIFY_SECRET", "art-dev-secret"),
    })
    headers["Authorization"] = "Bearer " + login["token"]
    if args.verify_existing:
        evidence = json.loads(args.output.read_text())
        path = "/api/v1/planning/scenarios/" + evidence["scenario_id"]
        assert request(path)["status"] == "completed"
        assert request(path + "/results") == evidence["results"]
        assert request(path + "/investment") == evidence["investment"]
        assert request("/api/v1/planning/baseline") == evidence["baseline"]
        print("Saved scenario, results, investment and baseline verified")
        return
    baseline = request("/api/v1/planning/baseline")
    infrastructure = baseline["infrastructure"]
    changed = {**infrastructure, "security_lanes_per_terminal": {
        **infrastructure["security_lanes_per_terminal"],
        "B": infrastructure["security_lanes_per_terminal"]["B"] + 1,
    }}
    body = {
        "name": "UI verification — isolated Terminal B lane",
        "description": "Synthetic UI verification. Does not change the shared airport.",
        "horizon": "day", "monte_carlo_runs": 2, "random_seed": 16112026,
        "demand_source": "simulation", "weather_source": "simulation",
        "infrastructure": changed,
    }
    created = request("/api/v1/planning/scenarios", body)
    scenario_id = created["scenario_id"]
    path = "/api/v1/planning/scenarios/" + scenario_id
    deadline = time.monotonic() + 180
    statuses = []
    while True:
        status = request(path + "/status")
        if not statuses or status["status"] != statuses[-1]["status"]:
            statuses.append(status)
            print(status["status"], flush=True)
        if status["status"] in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Planning job did not finish within 180 seconds")
        time.sleep(2)
    if status["status"] != "completed":
        raise RuntimeError(str(status))
    detail = request(path)
    results = request(path + "/results")
    investment = request(path + "/investment")
    assert detail["random_seed"] == body["random_seed"]
    assert results.get("accounting_policy") == "airport-v1", "Legacy backend financial contract"
    assert investment.get("accounting_policy") == "airport-v1"
    assert results["kpis"] and results["baseline_kpis"] and results["delta_vs_baseline"]
    assert request(path + "/results") == results, "Persisted results changed on reread"
    assert request("/api/v1/planning/baseline") == baseline, "Baseline mutated"
    evidence = {
        "gateway": args.gateway, "scenario_id": scenario_id,
        "request": body, "baseline": baseline, "statuses": statuses,
        "detail": detail, "results": results, "investment": investment,
        "baseline_unchanged": True, "results_reread_identical": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print(f"Verified scenario {scenario_id}; evidence: {args.output}")


if __name__ == "__main__":
    main()

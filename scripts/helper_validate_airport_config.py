#!/usr/bin/env python3
"""Validate and preview airport config normalization.

Usage:
  python scripts/helper_validate_airport_config.py
  python scripts/helper_validate_airport_config.py --path config/airport.yaml
  python scripts/helper_validate_airport_config.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_airport_config_module(repo_root: Path):
    module_path = repo_root / "services" / "sim-orchestrator" / "services" / "airport_config.py"
    spec = importlib.util.spec_from_file_location("airport_config", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _runtime_to_dict(runtime: Any) -> dict[str, Any]:
    return {
        "identity": {
            "name": runtime.identity.name,
            "iata": runtime.identity.iata,
            "icao": runtime.identity.icao,
            "timezone": runtime.identity.timezone,
        },
        "infrastructure": {
            "terminal_codes": runtime.terminal_codes,
            "gates_per_terminal": runtime.gates_per_terminal_map,
            "total_gates": runtime.total_gates,
            "runway_pairs": [
                {
                    "id": r.id,
                    "length_m": r.length_m,
                    "ils": r.ils,
                }
                for r in runtime.runway_pairs
            ],
            "runway_directions": runtime.runway_directions,
            "departure_runway_ids": runtime.departure_runway_ids,
            "arrival_runway_ids": runtime.arrival_runway_ids,
        },
        "simulation": {
            "daily_flight_target": runtime.simulation.daily_flight_target,
            "load_factor_mean": runtime.simulation.load_factor_mean,
            "peak_hours": runtime.simulation.peak_hours,
            "load_factor_beta_params": runtime.load_factor_beta_params,
        },
        "airlines": [
            {
                "code": a.code,
                "market_share": a.market_share,
                "hub_terminal": a.hub_terminal,
            }
            for a in runtime.airlines
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate airport.yaml and show normalized runtime config")
    parser.add_argument("--path", default="config/airport.yaml", help="Path to airport config YAML")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    config_path = (repo_root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path)
    os.environ["AIRPORT_CONFIG_PATH"] = str(config_path)

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        return 2

    try:
        module = _load_airport_config_module(repo_root)
        runtime = module.load_airport_runtime_config(force_reload=True)
    except Exception as exc:
        print(f"ERROR: Invalid airport config: {exc}")
        return 1

    payload = _runtime_to_dict(runtime)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Airport config is valid.")
        print(f"Name: {runtime.identity.name}")
        print(f"Codes: {runtime.identity.iata}/{runtime.identity.icao}")
        print(f"Terminals: {', '.join(runtime.terminal_codes)}")
        print(f"Total gates: {runtime.total_gates}")
        print(f"Runway directions: {', '.join(d['id'] for d in runtime.runway_directions)}")
        print(f"Daily flights: {runtime.simulation.daily_flight_target}")
        print(f"Load factor mean: {runtime.simulation.load_factor_mean:.2f}")
        print(f"Peak hours: {runtime.simulation.peak_hours}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

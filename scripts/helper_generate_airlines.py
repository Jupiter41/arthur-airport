#!/usr/bin/env python3
"""Generate real-world airlines fixture from OpenFlights data.

Reads data/openflights/airlines.dat and data/openflights/routes.dat to produce
a realistic airlines.json fixture for the sim-orchestrator.

Usage:
    python scripts/helper_generate_airlines.py
    python scripts/helper_generate_airlines.py --count 15
    python scripts/helper_generate_airlines.py --output services/sim-orchestrator/fixtures/airlines.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# OpenFlights airlines.dat columns (no header):
# ID, Name, Alias, IATA, ICAO, Callsign, Country, Active
AIRLINE_COLS = ["id", "name", "alias", "iata", "icao", "callsign", "country", "active"]

# OpenFlights routes.dat columns (no header):
# Airline, AirlineID, SourceAirport, SourceAirportID, DestAirport, DestAirportID, Codeshare, Stops, Equipment
ROUTE_COLS = ["airline", "airline_id", "source", "source_id", "dest", "dest_id", "codeshare", "stops", "equipment"]

# Aircraft type mapping: OpenFlights equipment codes → our ICAO types
EQUIPMENT_MAP = {
    "738": "B738", "73H": "B738", "73W": "B738",
    "320": "A320", "32A": "A320", "32B": "A320",
    "321": "A321", "32Q": "A321",
    "77W": "B77W", "773": "B77W", "772": "B77W",
    "333": "A333", "330": "A333",
    "332": "A332",
    "E95": "E195", "E90": "E195", "E75": "E195",
    "DH4": "DH8D", "DH8": "DH8D", "AT7": "DH8D",
    "744": "B738",  # fallback for exotic types
    "787": "B77W",  # map 787 to B77W (similar long-haul)
    "359": "A333",  # A350 → A330 (similar)
}

# Terminal preference based on airline type/size
# Larger flag carriers → B, regionals → A, others → C
TERMINAL_RULES: dict[str, str] = {}

# Hand-picked airlines for a realistic mid-Atlantic hub
# Mix of: European flag carriers, low-cost, North American, African, Middle Eastern, South American
PREFERRED_AIRLINES = [
    # European flag carriers (high share — close to KART in the Atlantic)
    "BA",  # British Airways
    "AF",  # Air France
    "LH",  # Lufthansa
    "IB",  # Iberia
    "KL",  # KLM
    "TP",  # TAP Air Portugal (closest real airline geographically)
    # Low-cost European
    "FR",  # Ryanair
    "U2",  # easyJet
    # North American
    "AA",  # American Airlines
    "UA",  # United Airlines
    "DL",  # Delta Air Lines
    # Long-haul / diverse
    "EK",  # Emirates
    "ET",  # Ethiopian Airlines
    "LA",  # LATAM Airlines
    # Regional
    "S4",  # SATA International (Azores-based — perfect for KART!)
]


def load_airlines(airlines_path: Path) -> dict[str, dict]:
    """Load OpenFlights airlines.dat into a dict keyed by IATA code."""
    airlines: dict[str, dict] = {}
    with airlines_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 8:
                continue
            rec = dict(zip(AIRLINE_COLS, row))
            iata = rec.get("iata", "").strip()
            active = rec.get("active", "").strip()
            name = rec.get("name", "").strip()

            if not iata or iata == "\\N" or iata == "-" or len(iata) != 2:
                continue
            if active != "Y":
                continue
            if not name or name == "\\N":
                continue

            # Keep first (usually main) entry per IATA code
            if iata not in airlines:
                airlines[iata] = {
                    "code": iata,
                    "name": name,
                    "country": rec.get("country", "").strip(),
                    "icao": rec.get("icao", "").strip() if rec.get("icao") != "\\N" else "",
                    "callsign": rec.get("callsign", "").strip() if rec.get("callsign") != "\\N" else "",
                }
    return airlines


def load_route_equipment(routes_path: Path) -> dict[str, set[str]]:
    """Load routes.dat and extract equipment (aircraft) per airline IATA code."""
    airline_equipment: dict[str, set[str]] = {}
    with routes_path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 9:
                continue
            rec = dict(zip(ROUTE_COLS, row))
            airline_iata = rec.get("airline", "").strip()
            equipment_raw = rec.get("equipment", "").strip()

            if not airline_iata or not equipment_raw:
                continue

            for equip in equipment_raw.split(" "):
                equip = equip.strip()
                if equip and equip in EQUIPMENT_MAP:
                    airline_equipment.setdefault(airline_iata, set()).add(EQUIPMENT_MAP[equip])

    return airline_equipment


def assign_terminal(airline: dict, idx: int) -> str:
    """Assign terminal preference based on airline characteristics."""
    # Flag carriers and large airlines → Terminal B (largest, central)
    # Low-cost → Terminal C
    # Regional → Terminal A
    name_lower = airline["name"].lower()
    if any(kw in name_lower for kw in ["ryanair", "easyjet", "wizz", "vueling"]):
        return "C"
    if any(kw in name_lower for kw in ["regional", "sata", "express"]):
        return "A"
    # Distribute remaining among B (primary) and A/C
    return ["B", "A", "C"][idx % 3]


def assign_market_share(airlines: list[dict]) -> list[dict]:
    """Assign realistic market shares.

    Top 3 get highest share, then declining. Total normalizes to 1.0.
    """
    raw_shares = []
    for i, airline in enumerate(airlines):
        # Geometric decay: first airline gets most traffic
        share = 0.20 * (0.75 ** i)
        raw_shares.append(share)

    total = sum(raw_shares)
    for i, airline in enumerate(airlines):
        airline["market_share"] = round(raw_shares[i] / total, 3)

    return airlines


def build_fleet(airline_code: str, equipment: dict[str, set[str]]) -> list[str]:
    """Build fleet list for an airline from route equipment data."""
    fleet = sorted(equipment.get(airline_code, set()))
    if not fleet:
        # Default fleet for unknown airlines
        fleet = ["A320", "B738"]
    return fleet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate real-world airlines fixture from OpenFlights data"
    )
    parser.add_argument(
        "--airlines-dat",
        default="data/openflights/airlines.dat",
        help="Path to OpenFlights airlines.dat",
    )
    parser.add_argument(
        "--routes-dat",
        default="data/openflights/routes.dat",
        help="Path to OpenFlights routes.dat",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=15,
        help="Number of airlines to include (default: 15)",
    )
    parser.add_argument(
        "--output",
        default="services/sim-orchestrator/fixtures/airlines.json",
        help="Output JSON file path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Loading airlines from {args.airlines_dat}...")
    all_airlines = load_airlines(Path(args.airlines_dat))
    print(f"Found {len(all_airlines)} active airlines with IATA codes")

    print(f"Loading route equipment from {args.routes_dat}...")
    equipment = load_route_equipment(Path(args.routes_dat))
    print(f"Found equipment data for {len(equipment)} airlines")

    # Select preferred airlines that exist in the data
    selected: list[dict] = []
    for code in PREFERRED_AIRLINES:
        if code in all_airlines:
            airline = all_airlines[code]
            selected.append(airline)
        else:
            print(f"  Warning: {code} not found in airlines.dat, skipping")

    # If we need more, add top airlines by route count
    if len(selected) < args.count:
        existing_codes = {a["code"] for a in selected}
        remaining = [
            a for code, a in all_airlines.items()
            if code not in existing_codes and code in equipment
        ]
        # Sort by number of equipment types (proxy for route diversity)
        remaining.sort(key=lambda a: len(equipment.get(a["code"], set())), reverse=True)
        for a in remaining[: args.count - len(selected)]:
            selected.append(a)

    selected = selected[: args.count]

    # Assign fleet, terminal, market share
    for i, airline in enumerate(selected):
        airline["hub"] = "ART"
        airline["fleet"] = build_fleet(airline["code"], equipment)
        airline["preferred_terminal"] = assign_terminal(airline, i)

    selected = assign_market_share(selected)

    # Build output in the fixture schema
    output = []
    for airline in selected:
        output.append({
            "code": airline["code"],
            "name": airline["name"],
            "hub": "ART",
            "market_share": airline["market_share"],
            "preferred_terminal": airline["preferred_terminal"],
            "fleet": airline["fleet"],
        })

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(output)} airlines to {output_path}")
    for a in output:
        print(f"  {a['code']:>2s}  {a['name']:<30s}  T-{a['preferred_terminal']}  share={a['market_share']:.3f}  fleet={a['fleet']}")


if __name__ == "__main__":
    main()

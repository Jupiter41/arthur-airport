#!/usr/bin/env python3
"""Generate real-world destinations fixture from OurAirports data.

Reads data/ourairports/airports.csv and produces a destinations.json fixture
with real IATA codes, names, and distances from KART (38.75°N, 27.0833°W).

Usage:
    python scripts/helper_generate_destinations.py
    python scripts/helper_generate_destinations.py --airports-csv data/ourairports/airports.csv
    python scripts/helper_generate_destinations.py --count 80 --output services/sim-orchestrator/fixtures/destinations.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

# KART coordinates (fictional Azores-adjacent, open ocean)
KART_LAT = 38.75
KART_LON = -27.0833

# Distance thresholds in km (from ROADMAP.md §6.3)
MIN_DISTANCE_KM = 200
MAX_DISTANCE_KM = 12000
SHORT_HAUL_MAX_KM = 1500
MEDIUM_HAUL_MAX_KM = 4000

# Nautical miles per km
KM_TO_NM = 0.539957


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def classify_region(distance_km: float) -> str:
    """Classify route into region category based on distance from KART."""
    if distance_km < SHORT_HAUL_MAX_KM:
        return "domestic"
    elif distance_km < MEDIUM_HAUL_MAX_KM:
        return "shorthaul"
    else:
        return "longhaul"


# Major hub airports to always include (iconic destinations for a mid-Atlantic hub)
MUST_INCLUDE = {
    "LHR", "CDG", "JFK", "MAD", "FRA", "AMS", "FCO", "IST",  # European + US hubs
    "GRU", "NBO", "DXB", "JNB", "ACC", "ADD",  # Long-haul from KART
    "YYZ", "MIA", "ORD", "BOS", "EWR",  # North America
    "DAR", "DSS", "CMN", "LIS", "TFS",  # Africa + nearby
}


def compute_weight(distance_km: float, airport_type: str, iata: str = "") -> float:
    """Compute selection weight — closer airports and large airports get more traffic."""
    # Large airports get 5x weight over medium
    size_factor = 5.0 if airport_type == "large_airport" else 1.0

    # Must-include airports get massive boost
    if iata in MUST_INCLUDE:
        size_factor *= 10.0

    # Distance decay — shorter routes are more frequent
    if distance_km < SHORT_HAUL_MAX_KM:
        dist_factor = 3.0
    elif distance_km < MEDIUM_HAUL_MAX_KM:
        dist_factor = 2.0
    else:
        dist_factor = 1.0

    return size_factor * dist_factor


def build_candidate_pool(airports_csv: Path) -> list[dict]:
    """Read airports CSV and filter to eligible destinations."""
    candidates = []
    with airports_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            airport_type = (row.get("type") or "").strip()
            if airport_type not in {"large_airport", "medium_airport"}:
                continue

            iata = (row.get("iata_code") or "").strip().upper()
            if not iata or len(iata) != 3:
                continue

            try:
                lat = float(row["latitude_deg"])
                lon = float(row["longitude_deg"])
            except (TypeError, ValueError, KeyError):
                continue

            name = (row.get("name") or "").strip()
            if not name:
                continue

            distance_km = haversine_km(KART_LAT, KART_LON, lat, lon)
            if distance_km < MIN_DISTANCE_KM or distance_km > MAX_DISTANCE_KM:
                continue

            country = (row.get("iso_country") or "").strip()
            municipality = (row.get("municipality") or "").strip()

            candidates.append({
                "iata": iata,
                "name": name,
                "municipality": municipality,
                "country": country,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "distance_km": distance_km,
                "distance_nm": round(distance_km * KM_TO_NM),
                "airport_type": airport_type,
                "region": classify_region(distance_km),
                "raw_weight": compute_weight(distance_km, airport_type, iata),
            })

    # Deduplicate by IATA (prefer large_airport)
    by_iata: dict[str, dict] = {}
    for c in candidates:
        existing = by_iata.get(c["iata"])
        if existing is None:
            by_iata[c["iata"]] = c
        elif c["airport_type"] == "large_airport" and existing["airport_type"] != "large_airport":
            by_iata[c["iata"]] = c

    return sorted(by_iata.values(), key=lambda x: x["distance_km"])


def select_destinations(candidates: list[dict], count: int) -> list[dict]:
    """Select a diverse set of destinations from the candidate pool.

    Ensures geographic and distance diversity:
    - ~30% short-haul (domestic)
    - ~40% medium-haul (shorthaul)
    - ~30% long-haul

    Within each tier, must-include airports are picked first, then
    top-weighted airports with country diversity.
    """
    domestic = [c for c in candidates if c["region"] == "domestic"]
    shorthaul = [c for c in candidates if c["region"] == "shorthaul"]
    longhaul = [c for c in candidates if c["region"] == "longhaul"]

    target_domestic = max(5, round(count * 0.30))
    target_shorthaul = max(5, round(count * 0.40))
    target_longhaul = count - target_domestic - target_shorthaul

    selected: list[dict] = []

    for pool, target in [
        (domestic, target_domestic),
        (shorthaul, target_shorthaul),
        (longhaul, target_longhaul),
    ]:
        pool_sorted = sorted(pool, key=lambda x: x["raw_weight"], reverse=True)
        picked: list[dict] = []
        picked_iatas: set[str] = set()

        # First: must-include airports in this tier
        for c in pool_sorted:
            if len(picked) >= target:
                break
            if c["iata"] in MUST_INCLUDE and c["iata"] not in picked_iatas:
                picked.append(c)
                picked_iatas.add(c["iata"])

        # Second: one per country for diversity (top-weighted)
        countries_seen: set[str] = {c["country"] for c in picked}
        for c in pool_sorted:
            if len(picked) >= target:
                break
            if c["iata"] not in picked_iatas and c["country"] not in countries_seen:
                picked.append(c)
                picked_iatas.add(c["iata"])
                countries_seen.add(c["country"])

        # Third: fill remaining from top-weighted regardless of country
        for c in pool_sorted:
            if len(picked) >= target:
                break
            if c["iata"] not in picked_iatas:
                picked.append(c)
                picked_iatas.add(c["iata"])

        selected.extend(picked[:target])

    return selected


def normalize_weights(destinations: list[dict]) -> list[dict]:
    """Convert raw weights to normalized weights summing to 1.0."""
    total_weight = sum(d["raw_weight"] for d in destinations)
    result = []
    for d in destinations:
        weight = round(d["raw_weight"] / total_weight, 4) if total_weight > 0 else round(1.0 / len(destinations), 4)
        result.append({
            "iata": d["iata"],
            "name": d["name"],
            "distance_nm": d["distance_nm"],
            "region": d["region"],
            "weight": weight,
            "latitude_deg": d["latitude_deg"],
            "longitude_deg": d["longitude_deg"],
            "country": d["country"],
            "municipality": d["municipality"],
        })
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate real-world destinations fixture from OurAirports data"
    )
    parser.add_argument(
        "--airports-csv",
        default="data/ourairports/airports.csv",
        help="Path to OurAirports airports.csv",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=80,
        help="Number of destinations to select (default: 80)",
    )
    parser.add_argument(
        "--output",
        default="services/sim-orchestrator/fixtures/destinations.json",
        help="Output JSON file path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    airports_csv = Path(args.airports_csv)

    print(f"Reading airports from {airports_csv}...")
    candidates = build_candidate_pool(airports_csv)
    print(f"Found {len(candidates)} eligible airports within {MIN_DISTANCE_KM}-{MAX_DISTANCE_KM} km of KART")

    domestic = sum(1 for c in candidates if c["region"] == "domestic")
    shorthaul = sum(1 for c in candidates if c["region"] == "shorthaul")
    longhaul = sum(1 for c in candidates if c["region"] == "longhaul")
    print(f"  Domestic: {domestic}, Short-haul: {shorthaul}, Long-haul: {longhaul}")

    selected = select_destinations(candidates, args.count)
    destinations = normalize_weights(selected)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(destinations, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(destinations)} destinations to {output_path}")
    for region in ["domestic", "shorthaul", "longhaul"]:
        n = sum(1 for d in destinations if d["region"] == region)
        w = sum(d["weight"] for d in destinations if d["region"] == region)
        print(f"  {region}: {n} destinations, {w:.1%} total weight")


if __name__ == "__main__":
    main()

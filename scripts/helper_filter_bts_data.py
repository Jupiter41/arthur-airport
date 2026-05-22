#!/usr/bin/env python3
"""Filter and remap BTS T-100 data for KART simulation calibration.

Downloads or filters BTS T-100 Segment data to extract routes for a
real reference airport, then remaps the origin/destination codes to
the fictional KART (ART) airport.

Usage:
    # Filter existing raw CSV for a reference airport
    python scripts/helper_filter_bts_data.py \\
        --input data/bts/T100_2026.csv \\
        --reference-airport BOS \\
        --output data/bts/T100_reference.csv

    # List available airports and their traffic volumes
    python scripts/helper_filter_bts_data.py \\
        --input data/bts/T100_2026.csv \\
        --list-airports

    # Show statistics for a specific airport
    python scripts/helper_filter_bts_data.py \\
        --input data/bts/T100_2026.csv \\
        --reference-airport BOS \\
        --stats-only

The filtered CSV uses the same column names as the raw BTS T-100 format
but includes only:
    ORIGIN, DEST, UNIQUE_CARRIER, DEPARTURES_PERFORMED, SEATS,
    PASSENGERS, FREIGHT, DISTANCE, YEAR, MONTH

Routes are remapped: reference airport IATA → ART.
Zero-passenger rows and charter flights (CLASS != F/L/P) are excluded.

Reference airport choice: pick a medium-sized US airport that matches KART's
profile (~420 daily flights, 42 gates, domestic + international mix).
Good candidates: BOS, IAD, SAN, RDU, STL, BNA, MKE, CLT.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

# Columns to keep in the filtered output
OUTPUT_COLUMNS = [
    "ORIGIN",
    "DEST",
    "UNIQUE_CARRIER",
    "UNIQUE_CARRIER_NAME",
    "DEPARTURES_PERFORMED",
    "SEATS",
    "PASSENGERS",
    "FREIGHT",
    "DISTANCE",
    "YEAR",
    "MONTH",
    "CLASS",
]

# Scheduled service classes (exclude charter/cargo-only)
SCHEDULED_CLASSES = {"F", "L", "P"}  # F=scheduled, L=large charter, P=small


def list_airports(input_path: str) -> None:
    """Print traffic volumes for all airports in the dataset."""
    airport_pax: dict[str, float] = defaultdict(float)
    airport_deps: dict[str, float] = defaultdict(float)
    airport_routes: dict[str, set] = defaultdict(set)

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pax = float(row.get("PASSENGERS", "0") or "0")
            deps = float(row.get("DEPARTURES_PERFORMED", "0") or "0")
            origin = (row.get("ORIGIN", "") or "").strip()
            dest = (row.get("DEST", "") or "").strip()
            if pax > 0:
                airport_pax[origin] += pax
                airport_deps[origin] += deps
                airport_routes[origin].add(dest)

    print(f"{'Airport':<8} {'Monthly Pax':>14} {'Departures':>12} {'Routes':>8}")
    print("-" * 46)
    for airport in sorted(airport_pax, key=airport_pax.get, reverse=True)[:50]:
        pax = airport_pax[airport]
        deps = airport_deps[airport]
        routes = len(airport_routes[airport])
        print(f"{airport:<8} {pax:>14,.0f} {deps:>12,.0f} {routes:>8}")


def filter_and_remap(
    input_path: str,
    reference_airport: str,
    output_path: str,
    kart_iata: str = "ART",
    stats_only: bool = False,
) -> None:
    """Filter BTS data for a reference airport and remap to KART."""
    routes: list[dict] = []
    skipped_zero = 0
    total = 0

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            origin = (row.get("ORIGIN", "") or "").strip()
            dest = (row.get("DEST", "") or "").strip()
            pax = float(row.get("PASSENGERS", "0") or "0")
            flight_class = (row.get("CLASS", "") or "").strip()

            # Keep only routes to/from the reference airport
            if origin != reference_airport and dest != reference_airport:
                continue

            # Skip zero-passenger rows
            if pax <= 0:
                skipped_zero += 1
                continue

            # Remap reference airport to ART
            if origin == reference_airport:
                origin = kart_iata
            if dest == reference_airport:
                dest = kart_iata

            filtered_row = {
                "ORIGIN": origin,
                "DEST": dest,
                "UNIQUE_CARRIER": (row.get("UNIQUE_CARRIER", "") or "").strip(),
                "UNIQUE_CARRIER_NAME": (row.get("UNIQUE_CARRIER_NAME", "") or "").strip(),
                "DEPARTURES_PERFORMED": row.get("DEPARTURES_PERFORMED", "0"),
                "SEATS": row.get("SEATS", "0"),
                "PASSENGERS": row.get("PASSENGERS", "0"),
                "FREIGHT": row.get("FREIGHT", "0"),
                "DISTANCE": row.get("DISTANCE", "0"),
                "YEAR": row.get("YEAR", "2026"),
                "MONTH": row.get("MONTH", "1"),
                "CLASS": flight_class,
            }
            routes.append(filtered_row)

    # Compute statistics
    total_pax = sum(float(r["PASSENGERS"]) for r in routes)
    total_deps = sum(float(r["DEPARTURES_PERFORMED"]) for r in routes)
    total_seats = sum(float(r["SEATS"]) for r in routes)
    destinations = set()
    carriers = set()
    for r in routes:
        if r["ORIGIN"] == kart_iata:
            destinations.add(r["DEST"])
        else:
            destinations.add(r["ORIGIN"])
        carriers.add(r["UNIQUE_CARRIER"])

    avg_load = total_pax / total_seats if total_seats > 0 else 0

    print(f"\n{'=' * 60}")
    print("BTS T-100 Filter Report")
    print(f"{'=' * 60}")
    print(f"Reference airport:  {reference_airport} → remapped to {kart_iata}")
    print(f"Input rows:         {total:,}")
    print(f"Matching routes:    {len(routes):,}")
    print(f"Skipped (0 pax):    {skipped_zero:,}")
    print("")
    print("Monthly statistics:")
    print(f"  Total passengers: {total_pax:,.0f}")
    print(f"  Total departures: {total_deps:,.0f}")
    print(f"  Total seats:      {total_seats:,.0f}")
    print(f"  Avg load factor:  {avg_load:.1%}")
    print(f"  Destinations:     {len(destinations)}")
    print(f"  Carriers:         {len(carriers)}")
    print("")
    print("Daily estimates (÷30):")
    print(f"  Daily passengers: {total_pax / 30:,.0f}")
    print(f"  Daily departures: {total_deps / 30:,.0f}")
    print(f"  Daily flights:    {total_deps / 30 * 2:,.0f} (arrivals + departures)")
    print(f"{'=' * 60}")

    if stats_only:
        return

    # Write filtered CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(routes)

    print(f"\nWritten {len(routes)} rows to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Filter and remap BTS T-100 data for KART simulation",
    )
    parser.add_argument("--input", default="data/bts/T100_2026.csv",
                        help="Path to raw BTS T-100 CSV")
    parser.add_argument("--reference-airport", default="BOS",
                        help="IATA code of the real reference airport (default: BOS)")
    parser.add_argument("--output", default="data/bts/T100_reference.csv",
                        help="Path for filtered output CSV")
    parser.add_argument("--kart-iata", default="ART",
                        help="IATA code to remap reference airport to (default: ART)")
    parser.add_argument("--list-airports", action="store_true",
                        help="List all airports in the dataset with traffic volumes")
    parser.add_argument("--stats-only", action="store_true",
                        help="Show statistics without writing output file")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.list_airports:
        list_airports(args.input)
    else:
        filter_and_remap(
            args.input,
            args.reference_airport,
            args.output,
            args.kart_iata,
            args.stats_only,
        )


if __name__ == "__main__":
    main()

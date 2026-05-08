#!/usr/bin/env python3
"""Generate GeoJSON fixtures for Arthur International Airport (KART).

Creates airport topology (runways, taxiways, terminals, gates, apron)
centred on the canonical KART coordinates (49.6233°N, 6.2044°E).

Airport config:
  - 2 parallel runways: 09L/27R and 09R/27L (heading 090°), 3500m long
  - 3 terminals: A, B, C with 14 gates each
  - Taxiways connecting runways to terminal area
  - Apron surrounding the terminal/gate area

Usage:
    python scripts/helper_transform_geojson.py
"""

import json
import math
import os

GEOJSON_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "dashboards",
    "art-dashboard",
    "public",
    "geojson",
)

KART_LAT = 49.6233
KART_LON = 6.2044

# Conversion factors at KART latitude
DEG_LAT_PER_M = 1.0 / 111_320.0  # ~8.98e-6
DEG_LON_PER_M = 1.0 / (111_320.0 * math.cos(math.radians(KART_LAT)))  # ~13.86e-6


def offset(lat_m: float = 0, lon_m: float = 0) -> tuple[float, float]:
    """Return [lon, lat] offset from KART center by metres."""
    return (
        round(KART_LON + lon_m * DEG_LON_PER_M, 6),
        round(KART_LAT + lat_m * DEG_LAT_PER_M, 6),
    )


def rect(cx_m: float, cy_m: float, w_m: float, h_m: float) -> list:
    """Return a closed polygon ring [lon,lat] for a rectangle centred at (cx,cy) in metres."""
    hw, hh = w_m / 2, h_m / 2
    return [
        list(offset(cy_m + hh, cx_m - hw)),
        list(offset(cy_m + hh, cx_m + hw)),
        list(offset(cy_m - hh, cx_m + hw)),
        list(offset(cy_m - hh, cx_m - hw)),
        list(offset(cy_m + hh, cx_m - hw)),  # close ring
    ]


def write_geojson(filename: str, features: list[dict]) -> None:
    path = os.path.join(GEOJSON_DIR, filename)
    data = {"type": "FeatureCollection", "features": features}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  Wrote {filename} ({len(features)} features)")


def generate_runways() -> None:
    """Two parallel east-west runways, 3500m long, 60m wide, 300m apart."""
    length = 3500
    width = 60
    sep = 300  # vertical separation between runway centres

    features = []
    for i, (rid, name, y_off) in enumerate([
        ("09L-27R", "Runway 09L/27R", sep / 2),
        ("09R-27L", "Runway 09R/27L", -sep / 2),
    ]):
        features.append({
            "type": "Feature",
            "properties": {"id": rid, "name": name, "heading": 90, "height_m": 1.2},
            "geometry": {
                "type": "Polygon",
                "coordinates": [rect(0, y_off, length, width)],
            },
        })

    write_geojson("runways.geojson", features)


def generate_taxiways() -> None:
    """Three parallel taxiways between and around the runways."""
    length = 3000
    features = []
    for tid, name, y_off in [
        ("alpha", "Taxiway Alpha", 250),
        ("bravo", "Taxiway Bravo", 0),
        ("charlie", "Taxiway Charlie", -250),
    ]:
        coords = [
            list(offset(y_off, -length / 2)),
            list(offset(y_off, length / 2)),
        ]
        features.append({
            "type": "Feature",
            "properties": {"id": tid, "name": name},
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    write_geojson("taxiways.geojson", features)


def generate_terminals() -> None:
    """Three terminals north of the runway pair."""
    width = 600
    depth = 80
    base_y = 450  # north of runway centre
    gap = 30

    features = []
    for i, (tid, name, height) in enumerate([
        ("terminal-a", "Terminal A", 22),
        ("terminal-b", "Terminal B", 20),
        ("terminal-c", "Terminal C", 18),
    ]):
        cy = base_y - i * (depth + gap)
        features.append({
            "type": "Feature",
            "properties": {"id": tid, "name": name, "height_m": height},
            "geometry": {
                "type": "Polygon",
                "coordinates": [rect(0, cy, width, depth)],
            },
        })

    write_geojson("terminals.geojson", features)


def generate_gates() -> None:
    """14 gates per terminal, spaced along the south face of each terminal."""
    num_gates = 14
    width = 600
    base_y = 450
    depth = 80
    gap = 30
    spacing = width / (num_gates + 1)

    features = []
    for t_idx, terminal in enumerate(["A", "B", "C"]):
        cy = base_y - t_idx * (depth + gap) - depth / 2 - 10  # just south of terminal
        for g in range(1, num_gates + 1):
            gx = -width / 2 + g * spacing
            features.append({
                "type": "Feature",
                "properties": {"id": f"{terminal}{g:02d}", "terminal": terminal},
                "geometry": {
                    "type": "Point",
                    "coordinates": list(offset(cy, gx)),
                },
            })

    write_geojson("gates.geojson", features)


def generate_apron() -> None:
    """Main apron area surrounding the terminal complex."""
    features = [{
        "type": "Feature",
        "properties": {"id": "apron-main", "name": "Main Apron"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [rect(0, 400, 800, 400)],
        },
    }]
    write_geojson("apron.geojson", features)


def main() -> None:
    geojson_dir = os.path.normpath(GEOJSON_DIR)
    os.makedirs(geojson_dir, exist_ok=True)
    print(f"Generating GeoJSON fixtures in: {geojson_dir}")
    print(f"Center: ({KART_LAT}°N, {KART_LON}°E)")

    generate_runways()
    generate_taxiways()
    generate_terminals()
    generate_gates()
    generate_apron()

    print("Done.")


if __name__ == "__main__":
    main()

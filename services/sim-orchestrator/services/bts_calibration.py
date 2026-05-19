"""BTS T-100 data calibration for simulation parameters.

Loads BTS T-100 segment CSV and extracts per-route load factors,
departure frequencies, and capacity distributions that directly
calibrate the simulation's schedule generation and passenger models.

BTS fields used:
    DEPARTURES_PERFORMED → route frequency weights (replaces uniform destination weights)
    PASSENGERS / SEATS   → per-route load factor (replaces global beta distribution)
    SEATS                → seat capacity calibration
    MONTH                → seasonal variation curves

This module is consumed by:
    - schedule.py:    BTS-weighted destination sampling
    - passengers.py:  per-route load factor override
"""

from __future__ import annotations

import csv
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default path inside container (mounted via docker-compose volume)
_DEFAULT_BTS_PATH = "/app/data/bts/T100_2026.csv"


@dataclass(frozen=True)
class RouteCalibration:
    """Calibration data for a single origin–destination route."""
    origin: str
    destination: str
    monthly_departures: float
    monthly_seats: float
    monthly_passengers: float

    @property
    def load_factor(self) -> float:
        """Passengers / seats — the core BTS load factor metric."""
        return self.monthly_passengers / self.monthly_seats if self.monthly_seats > 0 else 0.8

    @property
    def pax_per_departure(self) -> float:
        return self.monthly_passengers / self.monthly_departures if self.monthly_departures > 0 else 0.0

    @property
    def avg_seat_capacity(self) -> int:
        """Average seat capacity per departure on this route."""
        return round(self.monthly_seats / self.monthly_departures) if self.monthly_departures > 0 else 180


@dataclass
class BTSCalibrationData:
    """Aggregated BTS calibration data used by schedule and passenger generators.

    Fields map to simulation logic as follows:
        route_weights     → schedule.py: _sample_destination() weight override
        route_load_factors → passengers.py: per-route load factor (replaces global beta)
        seasonal_factors  → passengers.py: month-based load factor adjustment
        capacity_profile  → schedule.py: seat capacity validation
    """
    # {destination_iata: total_departures} — used to weight destination selection
    route_weights: dict[str, float] = field(default_factory=dict)

    # {(origin, destination): load_factor} — per-route load factor
    route_load_factors: dict[tuple[str, str], float] = field(default_factory=dict)

    # {month: avg_load_factor} — seasonal variation
    seasonal_factors: dict[int, float] = field(default_factory=dict)

    # {destination_iata: avg_seat_capacity} — capacity constraints per route
    capacity_profile: dict[str, int] = field(default_factory=dict)

    # Global average load factor from BTS data
    global_load_factor: float = 0.80

    # Total routes loaded
    total_routes: int = 0

    # Whether BTS data was successfully loaded
    loaded: bool = False

    # Source file path
    source_path: str = ""


# Module-level singleton
_calibration: BTSCalibrationData | None = None


def load_bts_calibration(csv_path: str | None = None) -> BTSCalibrationData:
    """Load and parse BTS T-100 data into calibration parameters.

    This function is idempotent — subsequent calls return the cached result.
    """
    global _calibration
    if _calibration is not None and _calibration.loaded:
        return _calibration

    path = Path(csv_path or os.getenv("BTS_CSV_PATH", _DEFAULT_BTS_PATH))
    cal = BTSCalibrationData(source_path=str(path))

    if not path.exists():
        logger.warning("BTS CSV not found at %s — using default simulation parameters", path)
        _calibration = cal
        return cal

    try:
        _parse_bts_csv(path, cal)
        cal.loaded = True
        logger.info(
            "BTS calibration loaded: %d routes, global load factor %.3f from %s",
            cal.total_routes, cal.global_load_factor, path,
        )
    except Exception:
        logger.exception("Failed to parse BTS CSV at %s — using defaults", path)

    _calibration = cal
    return cal


def get_bts_calibration() -> BTSCalibrationData:
    """Get the current BTS calibration (loads lazily if needed)."""
    if _calibration is None:
        return load_bts_calibration()
    return _calibration


def get_route_load_factor(origin: str, destination: str) -> float | None:
    """Get BTS-calibrated load factor for a specific route.

    Returns None if no BTS data is available for this route,
    letting the caller fall back to the default beta distribution.
    """
    cal = get_bts_calibration()
    if not cal.loaded:
        return None
    return cal.route_load_factors.get((origin, destination))


def get_seasonal_load_factor(month: int) -> float | None:
    """Get BTS-derived seasonal load factor adjustment for a month.

    Returns None if no BTS data is available.
    """
    cal = get_bts_calibration()
    if not cal.loaded:
        return None
    return cal.seasonal_factors.get(month)


def get_destination_weights() -> dict[str, float] | None:
    """Get BTS-calibrated destination weights for schedule generation.

    Returns {iata: weight} dict or None if BTS data unavailable.
    Weights are based on total departure frequency from BTS data.
    """
    cal = get_bts_calibration()
    if not cal.loaded or not cal.route_weights:
        return None
    return dict(cal.route_weights)


def _parse_bts_csv(path: Path, cal: BTSCalibrationData) -> None:
    """Parse the BTS T-100 CSV and populate calibration data.

    Aggregates across carriers to get per-route totals,
    then derives load factors, weights, and seasonal curves.
    """
    # Accumulate per (origin, dest) and per month
    route_agg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    month_agg: dict[int, list[float]] = defaultdict(list)

    count = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                deps = float(row.get("DEPARTURES_PERFORMED", "0") or "0")
                seats = float(row.get("SEATS", "0") or "0")
                passengers = float(row.get("PASSENGERS", "0") or "0")
                origin = (row.get("ORIGIN", "") or "").strip()
                dest = (row.get("DEST", "") or "").strip()
                month = int(row.get("MONTH", "1") or "1")

                if deps <= 0 and seats <= 0 and passengers <= 0:
                    continue  # Skip empty records

                route_agg[(origin, dest)].append({
                    "departures": deps,
                    "seats": seats,
                    "passengers": passengers,
                    "month": month,
                })

                if seats > 0:
                    month_agg[month].append(passengers / seats)

                count += 1
            except (ValueError, KeyError):
                continue

    # Build per-route calibration
    all_load_factors = []
    dest_departures: dict[str, float] = defaultdict(float)

    for (origin, dest), records in route_agg.items():
        total_deps = sum(r["departures"] for r in records)
        total_seats = sum(r["seats"] for r in records)
        total_pax = sum(r["passengers"] for r in records)

        if total_seats > 0:
            lf = total_pax / total_seats
            cal.route_load_factors[(origin, dest)] = round(max(0.1, min(1.0, lf)), 4)
            all_load_factors.append(lf)

        if total_deps > 0:
            dest_departures[dest] += total_deps

        if total_deps > 0 and total_seats > 0:
            cal.capacity_profile[dest] = round(total_seats / total_deps)

    # Normalize destination weights
    if dest_departures:
        max_deps = max(dest_departures.values())
        cal.route_weights = {
            dest: round(deps / max_deps, 4)
            for dest, deps in dest_departures.items()
        }

    # Seasonal load factors
    for month, factors in sorted(month_agg.items()):
        cal.seasonal_factors[month] = round(sum(factors) / len(factors), 4) if factors else 0.8

    # Global average
    if all_load_factors:
        cal.global_load_factor = round(sum(all_load_factors) / len(all_load_factors), 4)

    cal.total_routes = len(route_agg)
    logger.info(
        "BTS parsed %d records → %d unique routes, %d months, global LF=%.3f",
        count, cal.total_routes, len(cal.seasonal_factors), cal.global_load_factor,
    )

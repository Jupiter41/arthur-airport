"""BTS (Bureau of Transportation Statistics) historical passenger data adapter.

Loads T-100 segment CSV data and provides per-route hourly passenger flow
distributions based on real US DOT passenger statistics.

Data source: https://www.transtats.bts.gov/
Dataset: T-100 Domestic/International Segment (monthly aggregates)

The adapter disaggregates monthly totals into hourly profiles using a
standard airport diurnal pattern curve, making the data compatible with
the simulation's per-tick passenger flow model.
"""

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RoutePassengerStats:
    """Aggregated passenger statistics for a single route."""

    origin: str
    destination: str
    carrier: str
    departures_performed: int
    seats: int
    passengers: int
    month: int
    year: int

    @property
    def load_factor(self) -> float:
        return self.passengers / self.seats if self.seats > 0 else 0.0

    @property
    def pax_per_departure(self) -> float:
        return self.passengers / self.departures_performed if self.departures_performed > 0 else 0.0


@dataclass
class HourlyPassengerProfile:
    """Passenger distribution across hours of a day."""

    # Standard airport diurnal pattern (fraction of daily total per hour)
    # Based on typical European/US hub traffic curves
    HOURLY_WEIGHTS: list[float] = field(default_factory=lambda: [
        0.005, 0.003, 0.002, 0.002, 0.005, 0.020,  # 00-05
        0.045, 0.075, 0.085, 0.080, 0.075, 0.070,  # 06-11
        0.065, 0.070, 0.075, 0.070, 0.065, 0.060,  # 12-17
        0.055, 0.040, 0.030, 0.020, 0.010, 0.003,  # 18-23
    ])

    def get_hourly_fraction(self, hour: int) -> float:
        """Return fraction of daily passengers for given hour (0-23)."""
        if 0 <= hour < 24:
            return self.HOURLY_WEIGHTS[hour]
        return 0.0


@dataclass
class BTSFlowSnapshot:
    """Passenger flow data for a specific time window."""

    total_passengers: int
    departing_passengers: int
    arriving_passengers: int
    avg_load_factor: float
    zone_counts: dict[str, int]
    route_breakdown: list[dict]


class BTSPassengerSource:
    """Bureau of Transportation Statistics historical passenger data adapter.

    Loads T-100 segment data and maps it to per-hour passenger flow counts.
    Simulation days are mapped to historical months cyclically.
    """

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self._csv_path = Path(csv_path) if csv_path else None
        self._routes: list[RoutePassengerStats] = []
        self._by_origin: dict[str, list[RoutePassengerStats]] = defaultdict(list)
        self._by_dest: dict[str, list[RoutePassengerStats]] = defaultdict(list)
        self._daily_total: int = 0
        self._avg_load_factor: float = 0.8
        self._loaded = False
        self._profile = HourlyPassengerProfile()
        self._home_icao: str = os.getenv("AIRPORT_ICAO", "KART")
        self._home_iata: str = os.getenv("AIRPORT_IATA", "ART")

    def load(self) -> int:
        """Load CSV data. Returns number of records loaded."""
        if self._csv_path is None or not self._csv_path.exists():
            logger.warning("BTS CSV not found at %s — generating sample data", self._csv_path)
            self._generate_sample_data()
            return len(self._routes)

        try:
            count = self._load_csv()
            # If no routes match the home airport, supplement with sample data
            home = self._home_iata
            home_routes = [r for r in self._routes if r.origin == home or r.destination == home]
            if not home_routes:
                logger.warning(
                    "BTS CSV loaded %d routes but none match home airport %s — adding sample data",
                    count, home,
                )
                self._generate_sample_data()
            return len(self._routes)
        except Exception as e:
            logger.error("Failed to load BTS CSV: %s — generating sample data", e)
            self._generate_sample_data()
            return len(self._routes)

    def _load_csv(self) -> int:
        """Parse BTS T-100 segment CSV format."""
        count = 0
        with open(self._csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    route = RoutePassengerStats(
                        origin=row.get("ORIGIN", row.get("origin", "")).strip(),
                        destination=row.get("DEST", row.get("dest", "")).strip(),
                        carrier=row.get("UNIQUE_CARRIER", row.get("carrier", "")).strip(),
                        departures_performed=int(row.get("DEPARTURES_PERFORMED",
                                                         row.get("departures", 0))),
                        seats=int(row.get("SEATS", row.get("seats", 0))),
                        passengers=int(row.get("PASSENGERS", row.get("passengers", 0))),
                        month=int(row.get("MONTH", row.get("month", 1))),
                        year=int(row.get("YEAR", row.get("year", 2023))),
                    )
                    if route.passengers > 0:
                        self._routes.append(route)
                        self._by_origin[route.origin].append(route)
                        self._by_dest[route.destination].append(route)
                        count += 1
                except (ValueError, KeyError) as e:
                    logger.debug("Skipping BTS row: %s", e)
                    continue

        self._compute_daily_stats()
        self._loaded = True
        logger.info("BTS adapter loaded %d routes from %s", count, self._csv_path)
        return count

    def _generate_sample_data(self) -> None:
        """Generate realistic sample BTS data for demonstration.

        Modelled on a medium-sized US airport (~8M annual pax, ~420 daily
        flights).  Monthly passenger counts are calibrated so that the
        hourly diurnal profile produces peak-hour totals comparable to the
        simulation engine (~5000 pax in airport at any given moment).
        """
        home = self._home_iata  # Use configured home airport
        # Sample routes — monthly pax calibrated for a medium hub
        # (monthly pax ≈ daily_flights * seats * load_factor * 30)
        sample_routes = [
            # (origin, dest, carrier, monthly_departures, seats, monthly_pax)
            (home, "JFK", "AX", 90, 189, 14200),
            (home, "LAX", "AX", 60, 189, 9500),
            (home, "LHR", "BA", 60, 220, 11800),
            (home, "CDG", "AF", 60, 180, 9100),
            (home, "FRA", "LH", 60, 180, 8900),
            (home, "ORD", "UA", 60, 189, 9600),
            (home, "DXB", "EK", 30, 396, 9900),
            (home, "AMS", "KL", 60, 180, 8700),
            (home, "NRT", "AX", 30, 300, 7500),
            (home, "SIN", "AX", 30, 300, 7200),
            (home, "YYZ", "AX", 60, 189, 9300),
            (home, "MUC", "LH", 60, 180, 8600),
            (home, "BCN", "AX", 30, 180, 4500),
            (home, "FCO", "AX", 30, 180, 4400),
            (home, "SYD", "AX", 15, 300, 3600),
            ("JFK", home, "AX", 90, 189, 13800),
            ("LAX", home, "AX", 60, 189, 9200),
            ("LHR", home, "BA", 60, 220, 11500),
            ("CDG", home, "AF", 60, 180, 8800),
            ("FRA", home, "LH", 60, 180, 8600),
            ("ORD", home, "UA", 60, 189, 9400),
            ("DXB", home, "EK", 30, 396, 9700),
            ("AMS", home, "KL", 60, 180, 8400),
        ]

        for origin, dest, carrier, deps, seats, pax in sample_routes:
            for month in range(1, 13):
                # Seasonal variation: summer +20%, winter -15%
                seasonal = 1.0
                if month in (6, 7, 8):
                    seasonal = 1.20
                elif month in (12, 1, 2):
                    seasonal = 0.85
                elif month in (3, 4, 5, 9, 10, 11):
                    seasonal = 1.0

                route = RoutePassengerStats(
                    origin=origin,
                    destination=dest,
                    carrier=carrier,
                    departures_performed=deps,
                    seats=seats,
                    passengers=int(pax * seasonal),
                    month=month,
                    year=2023,
                )
                self._routes.append(route)
                self._by_origin[route.origin].append(route)
                self._by_dest[route.destination].append(route)

        self._compute_daily_stats()
        self._loaded = True
        logger.info("BTS adapter generated %d sample route-months", len(self._routes))

    def _compute_daily_stats(self) -> None:
        """Compute daily passenger total from monthly data."""
        if not self._routes:
            return

        # Average across all months, convert to daily
        monthly_total = sum(r.passengers for r in self._routes)
        n_months = len(set((r.month, r.year) for r in self._routes))
        avg_monthly = monthly_total / n_months if n_months > 0 else 0
        self._daily_total = int(avg_monthly / 30)  # approximate daily

        total_seats = sum(r.seats * r.departures_performed for r in self._routes)
        total_pax = sum(r.passengers * r.departures_performed for r in self._routes)
        self._avg_load_factor = total_pax / total_seats if total_seats > 0 else 0.8

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def route_count(self) -> int:
        return len(set((r.origin, r.destination) for r in self._routes))

    @property
    def daily_total(self) -> int:
        return self._daily_total

    @property
    def avg_load_factor(self) -> float:
        return self._avg_load_factor

    def get_flow_at(self, sim_time: datetime) -> BTSFlowSnapshot:
        """Get passenger flow data for the given simulation time.

        Disaggregates monthly BTS totals into hourly estimates using
        a standard diurnal airport traffic pattern.
        """
        hour = sim_time.hour
        month = sim_time.month

        # Filter routes for the current month (cyclic)
        month_routes = [r for r in self._routes if r.month == month]
        if not month_routes:
            month_routes = self._routes  # fallback to all

        # Calculate hourly fraction
        hourly_frac = self._profile.get_hourly_fraction(hour)

        # Compute departing and arriving passengers
        home = self._home_iata
        departing_routes = [r for r in month_routes if r.origin == home]
        arriving_routes = [r for r in month_routes if r.destination == home]

        dep_monthly = sum(r.passengers for r in departing_routes)
        arr_monthly = sum(r.passengers for r in arriving_routes)
        dep_daily = dep_monthly / 30
        arr_daily = arr_monthly / 30
        dep_hourly = int(dep_daily * hourly_frac)
        arr_hourly = int(arr_daily * hourly_frac)
        total_hourly = dep_hourly + arr_hourly

        # Zone distribution estimate based on typical airport flow
        zone_counts = {
            "checkin": int(dep_hourly * 0.15),
            "security_queue": int(dep_hourly * 0.10),
            "airside": int(dep_hourly * 0.35),
            "at_gate": int(dep_hourly * 0.25),
            "boarding": int(dep_hourly * 0.15),
            "deplaning": int(arr_hourly * 0.30),
            "baggage_claim": int(arr_hourly * 0.40),
            "customs": int(arr_hourly * 0.15),
            "arrived": int(arr_hourly * 0.15),
        }

        # Route breakdown (top routes)
        route_breakdown = []
        for r in sorted(month_routes, key=lambda x: x.passengers, reverse=True)[:10]:
            route_breakdown.append({
                "origin": r.origin,
                "destination": r.destination,
                "carrier": r.carrier,
                "monthly_passengers": r.passengers,
                "estimated_daily": int(r.passengers / 30),
                "load_factor": round(r.load_factor, 2),
            })

        avg_lf = (
            sum(r.load_factor for r in month_routes) / len(month_routes)
            if month_routes else 0.8
        )

        return BTSFlowSnapshot(
            total_passengers=total_hourly,
            departing_passengers=dep_hourly,
            arriving_passengers=arr_hourly,
            avg_load_factor=round(avg_lf, 3),
            zone_counts=zone_counts,
            route_breakdown=route_breakdown,
        )

    def get_summary(self) -> dict:
        """Return summary statistics for the loaded BTS data."""
        return {
            "loaded": self._loaded,
            "csv_path": str(self._csv_path) if self._csv_path else None,
            "total_routes": self.route_count,
            "total_route_months": len(self._routes),
            "estimated_daily_passengers": self._daily_total,
            "avg_load_factor": round(self._avg_load_factor, 3),
            "home_airport": self._home_iata,
            "data_source": "csv" if self._csv_path and self._csv_path.exists() else "sample",
        }

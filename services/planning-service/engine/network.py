"""Network resilience & hub dependency analysis (2D — ROADMAP_USECASE.md).

Provides:
- Hub dependency scoring (Herfindahl index across airlines)
- Airline removal disruption simulation
- Diversification recommendations using gravity model

Uses BTS T-100 data adapter for real route-level statistics.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


# ── Models ──────────────────────────────────────────────────


@dataclass
class AirlineDependency:
    """Per-airline dependency metrics."""

    airline_code: str
    airline_name: str
    movement_share: float  # 0–1
    passenger_share: float  # 0–1
    seat_share: float  # 0–1
    route_count: int
    daily_departures: float


@dataclass
class HubDependencyScore:
    """Overall hub dependency scoring."""

    herfindahl_index: float  # 0–1 (1 = monopoly, 0 = perfect competition)
    concentration_rating: str  # "low" | "moderate" | "high" | "very_high"
    top_airline_share: float  # share of largest airline
    effective_airlines: float  # 1/HHI — "equivalent" number of equal-sized airlines
    airlines: list[AirlineDependency] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "herfindahl_index": round(self.herfindahl_index, 4),
            "concentration_rating": self.concentration_rating,
            "top_airline_share_pct": round(self.top_airline_share * 100, 1),
            "effective_airlines": round(self.effective_airlines, 1),
            "airlines": [
                {
                    "airline_code": a.airline_code,
                    "airline_name": a.airline_name,
                    "movement_share_pct": round(a.movement_share * 100, 1),
                    "passenger_share_pct": round(a.passenger_share * 100, 1),
                    "seat_share_pct": round(a.seat_share * 100, 1),
                    "route_count": a.route_count,
                    "daily_departures": round(a.daily_departures, 1),
                }
                for a in self.airlines
            ],
        }


@dataclass
class DisruptionImpact:
    """Impact of removing/reducing an airline's operations."""

    airline_code: str
    reduction_pct: float
    lost_daily_departures: float
    lost_daily_passengers: float
    lost_daily_seats: float
    affected_routes: int
    exclusive_routes_lost: int  # routes served only by this airline
    residual_gate_utilisation_pct: float
    revenue_impact_pct: float
    new_herfindahl: float
    new_concentration_rating: str

    def to_dict(self) -> dict:
        return {
            "airline_code": self.airline_code,
            "reduction_pct": self.reduction_pct,
            "lost_daily_departures": round(self.lost_daily_departures, 1),
            "lost_daily_passengers": round(self.lost_daily_passengers, 0),
            "lost_daily_seats": round(self.lost_daily_seats, 0),
            "affected_routes": self.affected_routes,
            "exclusive_routes_lost": self.exclusive_routes_lost,
            "residual_gate_utilisation_pct": round(self.residual_gate_utilisation_pct, 1),
            "revenue_impact_pct": round(self.revenue_impact_pct, 1),
            "new_herfindahl": round(self.new_herfindahl, 4),
            "new_concentration_rating": self.new_concentration_rating,
        }


@dataclass
class DiversificationRoute:
    """A recommended new route for diversification."""

    destination_iata: str
    destination_name: str
    distance_km: float
    estimated_daily_demand: float
    gravity_score: float
    serves_underserved_market: bool
    recommended_frequency: int  # daily flights
    recommended_aircraft: str

    def to_dict(self) -> dict:
        return {
            "destination_iata": self.destination_iata,
            "destination_name": self.destination_name,
            "distance_km": round(self.distance_km, 0),
            "estimated_daily_demand": round(self.estimated_daily_demand, 0),
            "gravity_score": round(self.gravity_score, 2),
            "serves_underserved_market": self.serves_underserved_market,
            "recommended_frequency": self.recommended_frequency,
            "recommended_aircraft": self.recommended_aircraft,
        }


# ── Helper: Herfindahl-Hirschman Index ──────────────────────


def _hhi_rating(hhi: float) -> str:
    """Classify HHI concentration level (US DOJ thresholds)."""
    if hhi < 0.15:
        return "low"
    elif hhi < 0.25:
        return "moderate"
    elif hhi < 0.50:
        return "high"
    return "very_high"


# ── Network analysis from BTS data ──────────────────────────


_DEFAULT_BTS_PATH = Path("data/bts/T100_reference.csv")

# Population data for gravity model (millions, approximate — used for demand estimation)
_CITY_POPULATIONS: dict[str, float] = {
    "LHR": 9.0, "JFK": 8.3, "LAX": 4.0, "CDG": 2.2, "FRA": 5.6,
    "DXB": 3.5, "SIN": 5.7, "HKG": 7.5, "NRT": 14.0, "ICN": 10.0,
    "AMS": 1.2, "MAD": 3.3, "BCN": 5.6, "FCO": 2.8, "MUC": 1.5,
    "IST": 15.5, "DOH": 2.4, "ATL": 6.1, "ORD": 2.7, "DFW": 7.6,
    "MIA": 6.2, "BOS": 4.9, "DEN": 2.9, "SFO": 0.9, "SEA": 4.0,
    "MSP": 3.7, "DTW": 4.4, "PHL": 6.2, "CLT": 2.7, "EWR": 8.3,
    "YYZ": 6.2, "YUL": 4.1, "MEX": 21.0, "GRU": 22.0, "BOG": 11.0,
    "LIS": 2.9, "DUB": 1.4, "ZRH": 1.4, "VIE": 1.9, "CPH": 1.3,
    "OSL": 1.0, "ARN": 1.6, "HEL": 1.3, "WAW": 1.8, "BRU": 2.1,
}

# KART coordinates (fictional mid-Atlantic hub — roughly Azores latitude)
_KART_LAT = 38.7
_KART_LON = -27.2
_KART_POP = 0.5  # millions (medium airport catchment)

# Airport coordinates for gravity model (lat, lon)
_AIRPORT_COORDS: dict[str, tuple[float, float]] = {
    "LHR": (51.47, -0.46), "JFK": (40.64, -73.78), "LAX": (33.94, -118.41),
    "CDG": (49.01, 2.55), "FRA": (50.03, 8.57), "DXB": (25.25, 55.36),
    "SIN": (1.36, 103.99), "HKG": (22.31, 113.91), "NRT": (35.76, 140.39),
    "ICN": (37.46, 126.44), "AMS": (52.31, 4.77), "MAD": (40.47, -3.57),
    "BCN": (41.30, 2.08), "FCO": (41.80, 12.24), "MUC": (48.35, 11.79),
    "IST": (41.26, 28.74), "DOH": (25.27, 51.61), "ATL": (33.64, -84.43),
    "ORD": (41.97, -87.91), "DFW": (32.90, -97.04), "MIA": (25.79, -80.29),
    "BOS": (42.36, -71.01), "DEN": (39.86, -104.67), "SFO": (37.62, -122.38),
    "SEA": (47.45, -122.31), "MSP": (44.88, -93.22), "DTW": (42.21, -83.35),
    "PHL": (39.87, -75.24), "CLT": (35.21, -80.94), "EWR": (40.69, -74.17),
    "YYZ": (43.68, -79.63), "YUL": (45.47, -73.74), "MEX": (19.44, -99.07),
    "GRU": (-23.43, -46.47), "BOG": (4.70, -74.15), "LIS": (38.77, -9.13),
    "DUB": (53.43, -6.27), "ZRH": (47.46, 8.55), "VIE": (48.11, 16.57),
    "CPH": (55.62, 12.66), "OSL": (60.19, 11.10), "ARN": (59.65, 17.92),
    "HEL": (60.32, 24.96), "WAW": (52.17, 20.97), "BRU": (50.90, 4.48),
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _gravity_demand(
    pop_origin: float, pop_dest: float, distance_km: float, k: float = 50.0
) -> float:
    """Gravity model demand estimate: demand ∝ pop_o × pop_d / distance².

    Returns estimated daily passengers (one-way).
    k is calibration constant (calibrated to match medium-hub airport traffic volumes).
    """
    if distance_km < 100:
        distance_km = 100  # prevent division by near-zero
    return k * (pop_origin * pop_dest * 1_000_000) / (distance_km ** 2)


class NetworkAnalyzer:
    """Analyzes route network concentration and resilience using BTS data."""

    def __init__(self, bts_csv_path: str | Path | None = None):
        if pd is None:
            raise ImportError("pandas is required for network analysis: pip install pandas")

        path = Path(bts_csv_path) if bts_csv_path else _DEFAULT_BTS_PATH
        self.df = pd.read_csv(path, low_memory=False)
        self.df.columns = self.df.columns.str.strip().str.upper()

        # Ensure numeric columns
        for col in ["PASSENGERS", "SEATS", "DEPARTURES_PERFORMED", "DISTANCE", "MONTH"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce").fillna(0)

    def compute_dependency(self) -> HubDependencyScore:
        """Compute hub dependency index (Herfindahl) across airlines."""
        # Aggregate by carrier
        carrier_col = "UNIQUE_CARRIER" if "UNIQUE_CARRIER" in self.df.columns else "CARRIER"
        name_col = "UNIQUE_CARRIER_NAME" if "UNIQUE_CARRIER_NAME" in self.df.columns else carrier_col

        by_carrier = (
            self.df.groupby(carrier_col)
            .agg({
                "DEPARTURES_PERFORMED": "sum",
                "PASSENGERS": "sum",
                "SEATS": "sum",
                "DEST": "nunique",
            })
            .reset_index()
        )

        # Get carrier names
        if name_col != carrier_col:
            names = self.df.groupby(carrier_col)[name_col].first().to_dict()
        else:
            names = {c: c for c in by_carrier[carrier_col]}

        total_deps = float(by_carrier["DEPARTURES_PERFORMED"].sum())
        total_pax = float(by_carrier["PASSENGERS"].sum())
        total_seats = float(by_carrier["SEATS"].sum())

        if total_deps == 0:
            return HubDependencyScore(
                herfindahl_index=0.0,
                concentration_rating="low",
                top_airline_share=0.0,
                effective_airlines=0.0,
            )

        # Compute shares and HHI
        airlines: list[AirlineDependency] = []
        hhi = 0.0

        # Estimate days in data for daily rate
        months = int(self.df["MONTH"].nunique()) if "MONTH" in self.df.columns else 12
        est_days = months * 30.5

        for _, row in by_carrier.iterrows():
            code = row[carrier_col]
            dep_share = float(row["DEPARTURES_PERFORMED"]) / total_deps if total_deps > 0 else 0.0
            pax_share = float(row["PASSENGERS"]) / total_pax if total_pax > 0 else 0.0
            seat_share = float(row["SEATS"]) / total_seats if total_seats > 0 else 0.0

            hhi += dep_share ** 2

            airlines.append(AirlineDependency(
                airline_code=str(code).strip(),
                airline_name=str(names.get(code, code)).strip(),
                movement_share=float(dep_share),
                passenger_share=float(pax_share),
                seat_share=float(seat_share),
                route_count=int(row["DEST"]),
                daily_departures=float(row["DEPARTURES_PERFORMED"]) / max(est_days, 1),
            ))

        airlines.sort(key=lambda a: -a.movement_share)
        top_share = float(airlines[0].movement_share) if airlines else 0.0
        effective = 1.0 / hhi if hhi > 0 else 0.0

        return HubDependencyScore(
            herfindahl_index=float(hhi),
            concentration_rating=_hhi_rating(hhi),
            top_airline_share=float(top_share),
            effective_airlines=float(effective),
            airlines=airlines[:20],  # Top 20 airlines
        )

    def simulate_disruption(
        self, airline_code: str, reduction_pct: float = 100.0
    ) -> DisruptionImpact:
        """Simulate the impact of an airline reducing or ceasing operations.

        Args:
            airline_code: IATA code of the airline to disrupt.
            reduction_pct: Percentage reduction (100 = full withdrawal).
        """
        carrier_col = "UNIQUE_CARRIER" if "UNIQUE_CARRIER" in self.df.columns else "CARRIER"
        reduction_factor = reduction_pct / 100.0

        airline_mask = self.df[carrier_col].str.strip() == airline_code
        airline_data = self.df[airline_mask]

        if airline_data.empty:
            return DisruptionImpact(
                airline_code=airline_code,
                reduction_pct=reduction_pct,
                lost_daily_departures=0.0,
                lost_daily_passengers=0.0,
                lost_daily_seats=0.0,
                affected_routes=0,
                exclusive_routes_lost=0,
                residual_gate_utilisation_pct=100.0,
                revenue_impact_pct=0.0,
                new_herfindahl=0.0,
                new_concentration_rating="low",
            )

        months = int(self.df["MONTH"].nunique()) if "MONTH" in self.df.columns else 12
        est_days = months * 30.5

        total_deps_all = float(self.df["DEPARTURES_PERFORMED"].sum())
        total_pax_all = float(self.df["PASSENGERS"].sum())

        airline_deps = float(airline_data["DEPARTURES_PERFORMED"].sum())
        airline_pax = float(airline_data["PASSENGERS"].sum())
        airline_seats = float(airline_data["SEATS"].sum())

        # Routes exclusively served by this airline
        airline_routes = set(str(d).strip() for d in airline_data["DEST"].unique())
        other_routes = set(str(d).strip() for d in self.df[~airline_mask]["DEST"].unique())
        exclusive_routes = airline_routes - other_routes

        lost_deps = airline_deps * reduction_factor
        lost_pax = airline_pax * reduction_factor
        lost_seats = airline_seats * reduction_factor

        # Residual gate utilisation (assuming 42 gates, 12h operating window)
        total_daily_deps = total_deps_all / max(est_days, 1)
        residual_daily_deps = total_daily_deps - (lost_deps / max(est_days, 1))
        # Each gate handles ~1 flight/hour for 12 hours = 12 flights/day capacity
        gate_capacity = 42 * 12
        residual_gate_util = min(100.0, (residual_daily_deps / gate_capacity) * 100)

        # Revenue impact (proportional to passengers lost)
        revenue_impact = (lost_pax / max(total_pax_all, 1)) * 100

        # New HHI after reduction
        remaining = self.df.copy()
        if reduction_pct >= 100:
            remaining = remaining[~airline_mask]
        else:
            # Reduce proportionally
            remaining.loc[airline_mask, "DEPARTURES_PERFORMED"] *= (1 - reduction_factor)
            remaining.loc[airline_mask, "PASSENGERS"] *= (1 - reduction_factor)

        new_total = float(remaining["DEPARTURES_PERFORMED"].sum())
        new_hhi = 0.0
        if new_total > 0:
            by_carrier = remaining.groupby(carrier_col)["DEPARTURES_PERFORMED"].sum()
            for deps in by_carrier:
                share = float(deps) / new_total
                new_hhi += share ** 2

        return DisruptionImpact(
            airline_code=airline_code,
            reduction_pct=reduction_pct,
            lost_daily_departures=float(lost_deps / max(est_days, 1)),
            lost_daily_passengers=float(lost_pax / max(est_days, 1)),
            lost_daily_seats=float(lost_seats / max(est_days, 1)),
            affected_routes=len(airline_routes),
            exclusive_routes_lost=len(exclusive_routes),
            residual_gate_utilisation_pct=float(residual_gate_util),
            revenue_impact_pct=float(revenue_impact),
            new_herfindahl=float(new_hhi),
            new_concentration_rating=_hhi_rating(new_hhi),
        )

    def recommend_diversification(
        self, target_hhi: float = 0.15, max_recommendations: int = 10
    ) -> list[DiversificationRoute]:
        """Recommend new routes to reduce hub concentration.

        Uses a gravity model: demand ∝ pop_origin × pop_dest / distance²
        Filters to destinations not already served (or underserved) in BTS data.
        """
        # Get currently served destinations
        served = set(str(d).strip() for d in self.df["DEST"].unique())

        # Score all potential destinations not currently served
        candidates: list[DiversificationRoute] = []

        for iata, (lat, lon) in _AIRPORT_COORDS.items():
            if iata in served:
                continue
            pop = _CITY_POPULATIONS.get(iata, 1.0)
            dist = _haversine_km(_KART_LAT, _KART_LON, lat, lon)

            if dist < 200 or dist > 12000:
                continue  # Too close or too far

            demand = _gravity_demand(_KART_POP, pop, dist)

            # Aircraft selection by distance
            if dist < 1500:
                aircraft = "A320"
            elif dist < 4000:
                aircraft = "A321"
            else:
                aircraft = "B77W"

            # Frequency: cap at realistic levels
            freq = max(1, min(7, int(demand / 100)))

            candidates.append(DiversificationRoute(
                destination_iata=iata,
                destination_name=f"{iata} hub",
                distance_km=float(dist),
                estimated_daily_demand=float(demand),
                gravity_score=float(demand),
                serves_underserved_market=bool(iata not in served),
                recommended_frequency=int(freq),
                recommended_aircraft=aircraft,
            ))

        # Sort by gravity score (highest demand first)
        candidates.sort(key=lambda c: -c.gravity_score)
        return candidates[:max_recommendations]

"""BTS T-100 adapter — reads US DOT Bureau of Transportation Statistics data.

BTS Form 41 T-100 provides monthly passenger and flight counts by airline,
origin, and destination for all US carriers. Free, public domain.

Source: https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FIM

Expected CSV columns:
    DEPARTURES_PERFORMED, SEATS, PASSENGERS, DISTANCE, ORIGIN, DEST,
    CARRIER, YEAR, MONTH, AIRCRAFT_TYPE
"""

from __future__ import annotations

import calendar
import math
import random
from datetime import date, datetime, time
from pathlib import Path

from .base import AbstractAdapter

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


# Aircraft type mapping: BTS numeric codes to ICAO designators
_BTS_AIRCRAFT_MAP: dict[int, str] = {
    621: "B738",
    624: "A320",
    625: "A321",
    690: "B77W",
    332: "A333",
    348: "E195",
    375: "DH8D",
    499: "AT75",
}

# Reverse mapping from common aircraft strings
_ICAO_FALLBACK = "A320"


class BTSAdapter(AbstractAdapter):
    """Adapter reading BTS T-100 market data from CSV files."""

    def __init__(self, csv_path: str | Path):
        if pd is None:
            raise ImportError("pandas is required for BTS adapter: pip install pandas")

        self._csv_path = Path(csv_path)
        self.df = pd.read_csv(self._csv_path, low_memory=False)
        self.df.columns = self.df.columns.str.strip().str.upper()

        # Ensure numeric columns
        for col in ["PASSENGERS", "SEATS", "DEPARTURES_PERFORMED", "DISTANCE", "MONTH", "YEAR"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce").fillna(0)

    @property
    def source_name(self) -> str:
        return f"BTS T-100 ({self._csv_path.name})"

    @property
    def is_real_data(self) -> bool:
        return True

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """Average daily passengers on a given O&D pair for a given month.

        Aggregates across all carriers and returns monthly_total / days_in_month.
        """
        mask = (
            (self.df["ORIGIN"] == origin)
            & (self.df["DEST"] == destination)
            & (self.df["MONTH"] == month)
        )
        rows = self.df[mask]
        if rows.empty:
            return 0.0

        monthly_pax = rows["PASSENGERS"].sum()
        # Use first available year for day count
        year = int(rows["YEAR"].iloc[0]) if "YEAR" in rows.columns else 2023
        days = calendar.monthrange(year, month)[1]
        return round(monthly_pax / days, 1)

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """Build a BTS-calibrated schedule for the given date.

        Uses actual departure frequencies and seat counts from BTS data,
        distributed across the day with a bimodal pattern.
        """
        month = sim_date.month
        rng = random.Random(sim_date.toordinal())

        # Get routes active in this month
        month_data = self.df[self.df["MONTH"] == month]
        if month_data.empty:
            return []

        # Group by route to get daily frequency
        routes = (
            month_data.groupby(["ORIGIN", "DEST", "CARRIER"])
            .agg({
                "DEPARTURES_PERFORMED": "sum",
                "PASSENGERS": "sum",
                "SEATS": "sum",
                "DISTANCE": "first",
                "AIRCRAFT_TYPE": "first",
            })
            .reset_index()
        )

        year = int(month_data["YEAR"].iloc[0]) if "YEAR" in month_data.columns else 2023
        days_in_month = calendar.monthrange(year, month)[1]

        flights: list[dict] = []
        for _, route in routes.iterrows():
            daily_deps = route["DEPARTURES_PERFORMED"] / days_in_month
            if daily_deps < 0.1:
                continue

            # Stochastic number of flights today
            n_flights = int(daily_deps)
            if rng.random() < (daily_deps - n_flights):
                n_flights += 1

            if n_flights == 0:
                continue

            avg_pax = int(route["PASSENGERS"] / max(route["DEPARTURES_PERFORMED"], 1))
            distance = float(route["DISTANCE"])
            aircraft_code = int(route["AIRCRAFT_TYPE"]) if not math.isnan(route["AIRCRAFT_TYPE"]) else 0
            aircraft_type = _BTS_AIRCRAFT_MAP.get(aircraft_code, _ICAO_FALLBACK)
            carrier = str(route["CARRIER"]).strip()

            for _ in range(n_flights):
                # Bimodal departure time
                if rng.random() < 0.5:
                    hour = max(0, min(23, int(rng.gauss(8.0, 2.5))))
                else:
                    hour = max(0, min(23, int(rng.gauss(18.0, 2.5))))
                minute = rng.randint(0, 59)

                dep_time = datetime.combine(sim_date, time(hour, minute))
                fnum = f"{carrier}{rng.randint(100, 9999):04d}"

                flights.append({
                    "flight_number": fnum,
                    "airline_code": carrier,
                    "origin_iata": str(route["ORIGIN"]).strip(),
                    "destination_iata": str(route["DEST"]).strip(),
                    "aircraft_type": aircraft_type,
                    "scheduled_departure": dep_time.isoformat(),
                    "pax_count": max(1, avg_pax + rng.randint(-20, 20)),
                    "distance_km": round(distance * 1.60934, 1),  # miles → km
                })

        flights.sort(key=lambda f: f["scheduled_departure"])
        return flights

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """BTS does not provide weather — returns empty list.

        Use a weather-specific adapter (mesonet) for weather data.
        """
        return []

    def get_route_summary(self, month: int | None = None) -> list[dict]:
        """Return aggregate route-level statistics — useful for reports."""
        df = self.df
        if month is not None:
            df = df[df["MONTH"] == month]

        routes = (
            df.groupby(["ORIGIN", "DEST"])
            .agg({
                "PASSENGERS": "sum",
                "DEPARTURES_PERFORMED": "sum",
                "SEATS": "sum",
                "DISTANCE": "first",
            })
            .reset_index()
        )
        routes["LOAD_FACTOR"] = routes["PASSENGERS"] / routes["SEATS"].replace(0, 1)

        return [
            {
                "origin": row["ORIGIN"],
                "destination": row["DEST"],
                "total_passengers": int(row["PASSENGERS"]),
                "total_departures": int(row["DEPARTURES_PERFORMED"]),
                "load_factor": round(float(row["LOAD_FACTOR"]), 3),
                "distance_miles": float(row["DISTANCE"]),
            }
            for _, row in routes.iterrows()
        ]

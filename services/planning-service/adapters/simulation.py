"""Simulation adapter — wraps the existing sim-orchestrator seed logic.

Uses the same bimodal schedule generator and synthetic weather as the live
simulation, providing a deterministic baseline for planning scenarios.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, time

from .base import AbstractAdapter

# Airport config — matches config/airport.yaml defaults
_DESTINATIONS = [
    ("JFK", "New York", 5750),
    ("LAX", "Los Angeles", 8900),
    ("ORD", "Chicago", 6700),
    ("LHR", "London", 600),
    ("CDG", "Paris", 350),
    ("FRA", "Frankfurt", 700),
    ("AMS", "Amsterdam", 500),
    ("DXB", "Dubai", 5200),
    ("NRT", "Tokyo", 9500),
    ("SIN", "Singapore", 10800),
    ("SYD", "Sydney", 16900),
    ("YYZ", "Toronto", 5400),
    ("MUC", "Munich", 750),
    ("BCN", "Barcelona", 1100),
    ("FCO", "Rome", 1200),
]

_AIRCRAFT_TYPES = ["B738", "A320", "A321", "B77W", "A333", "E195", "DH8D", "AT75"]
_AIRCRAFT_WEIGHTS = [0.25, 0.25, 0.15, 0.05, 0.05, 0.10, 0.10, 0.05]

_AIRLINES = [
    ("AR", "Arthur Air"),
    ("BA", "British Airways"),
    ("LH", "Lufthansa"),
    ("AF", "Air France"),
    ("EK", "Emirates"),
    ("UA", "United Airlines"),
]


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class SimulationAdapter(AbstractAdapter):
    """Adapter wrapping existing simulation schedule generation."""

    def __init__(self, daily_flight_target: int = 420, seed: int | None = None):
        self._daily_target = daily_flight_target
        self._seed = seed

    @property
    def source_name(self) -> str:
        return "simulation"

    @property
    def is_real_data(self) -> bool:
        return False

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """Generate a bimodal flight schedule for the given date."""
        rng = random.Random(self._seed if self._seed is not None else sim_date.toordinal())

        flights: list[dict] = []
        n_flights = self._daily_target + rng.randint(-20, 20)

        for i in range(n_flights):
            # Bimodal departure distribution: peaks at 08:00 and 18:00
            if rng.random() < 0.5:
                hour = max(0, min(23, int(rng.gauss(8.0, 2.5))))
            else:
                hour = max(0, min(23, int(rng.gauss(18.0, 2.5))))
            minute = rng.randint(0, 59)

            dest_iata, dest_name, dist_km = rng.choice(_DESTINATIONS)
            airline_code, _ = rng.choice(_AIRLINES)
            aircraft_type = rng.choices(_AIRCRAFT_TYPES, weights=_AIRCRAFT_WEIGHTS, k=1)[0]

            # Pax count based on aircraft type
            seat_map = {"B738": 189, "A320": 180, "A321": 220, "B77W": 396, "A333": 300, "E195": 120, "DH8D": 78, "AT75": 72}
            seats = seat_map.get(aircraft_type, 180)
            pax = int(seats * rng.uniform(0.65, 0.95))

            departure_dt = datetime.combine(sim_date, time(hour, minute))
            flight_number = f"{airline_code}{rng.randint(100, 9999):04d}"

            flights.append({
                "flight_number": flight_number,
                "airline_code": airline_code,
                "origin_iata": "ART",
                "destination_iata": dest_iata,
                "aircraft_type": aircraft_type,
                "scheduled_departure": departure_dt.isoformat(),
                "pax_count": pax,
                "distance_km": dist_km,
            })

        flights.sort(key=lambda f: f["scheduled_departure"])
        return flights

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """Generate synthetic weather for 24 hours."""
        rng = random.Random((self._seed or 0) + sim_date.toordinal())

        categories = ["CAVOK", "VMC", "IMC", "LIFR"]
        weights = [0.50, 0.30, 0.15, 0.05]

        sequence: list[dict] = []
        current = rng.choices(categories, weights=weights, k=1)[0]

        # Markov-style transitions
        transition = {
            "CAVOK": {"CAVOK": 0.80, "VMC": 0.15, "IMC": 0.04, "LIFR": 0.01},
            "VMC": {"CAVOK": 0.30, "VMC": 0.50, "IMC": 0.15, "LIFR": 0.05},
            "IMC": {"CAVOK": 0.05, "VMC": 0.25, "IMC": 0.55, "LIFR": 0.15},
            "LIFR": {"CAVOK": 0.02, "VMC": 0.08, "IMC": 0.30, "LIFR": 0.60},
        }

        for hour in range(24):
            probs = transition[current]
            next_states = list(probs.keys())
            next_weights = list(probs.values())
            current = rng.choices(next_states, weights=next_weights, k=1)[0]

            vis_map = {"CAVOK": 15000, "VMC": 8000, "IMC": 3000, "LIFR": 800}
            wind_base = {"CAVOK": 5, "VMC": 12, "IMC": 20, "LIFR": 25}

            sequence.append({
                "hour": hour,
                "category": current,
                "wind_speed_kt": round(wind_base[current] + rng.uniform(-3, 5), 1),
                "visibility_m": round(vis_map[current] + rng.uniform(-1000, 1000), 0),
            })

        return sequence

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """Return synthetic demand (no real data)."""
        # Base demand scaled by seasonal factor
        base = 500.0
        # Summer peak, winter trough
        seasonal = 1.0 + 0.3 * math.sin((month - 3) * math.pi / 6)
        return round(base * seasonal, 1)

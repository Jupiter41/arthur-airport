"""Abstract base adapter for planning data sources.

Every adapter must implement the three data retrieval methods:
- get_daily_schedule(): flight schedule for a given date
- get_weather_sequence(): hourly weather states for a given date
- get_passenger_demand(): expected daily pax for an O&D pair in a month

This allows the planning engine to swap between simulated, BTS, OpenSky,
and Mesonet data sources at runtime via the registry.
"""

from abc import ABC, abstractmethod
from datetime import date


class AbstractAdapter(ABC):
    """Base interface for all planning data adapters."""

    @abstractmethod
    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """Return a list of flight dicts for the given date.

        Each dict must contain:
            flight_number, airline_code, origin_iata, destination_iata,
            aircraft_type, scheduled_departure (ISO str), pax_count, distance_km
        """

    @abstractmethod
    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """Return hourly weather observation dicts for the given date.

        Each dict must contain:
            hour (int 0-23), category (CAVOK|VMC|IMC|LIFR),
            wind_speed_kt (float), visibility_m (float)
        """

    @abstractmethod
    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """Return expected daily passenger count for an O&D pair in a given month.

        Returns 0.0 if no data is available for the pair.
        """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source identifier for reports."""

    @property
    @abstractmethod
    def is_real_data(self) -> bool:
        """True if this adapter uses real-world data."""

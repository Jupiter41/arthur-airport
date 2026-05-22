"""OpenSky Network historical data adapter.

Reads historical flight data from OpenSky Network CSV exports.
The OpenSky Network provides free ADS-B-based flight tracking data.

Source: https://opensky-network.org/datasets/

This adapter is a stub — OpenSky provides flight trajectories (position,
altitude, velocity) rather than schedule data. It can be extended to
extract actual departure/arrival times for model calibration.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import AbstractAdapter

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


class OpenSkyAdapter(AbstractAdapter):
    """Adapter reading OpenSky Network flight data CSVs."""

    def __init__(self, csv_path: str | Path | None = None):
        self._csv_path = Path(csv_path) if csv_path else None
        self._df = None

        if self._csv_path and self._csv_path.exists():
            if pd is None:
                raise ImportError("pandas is required for OpenSky adapter: pip install pandas")
            self._df = pd.read_csv(self._csv_path, low_memory=False)
            self._df.columns = self._df.columns.str.strip().str.lower()

    @property
    def source_name(self) -> str:
        return f"OpenSky Network ({self._csv_path.name if self._csv_path else 'none'})"

    @property
    def is_real_data(self) -> bool:
        return True

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """OpenSky provides trajectory data, not schedules.

        Returns empty list — use BTS or simulation adapter for schedules.
        """
        return []

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """OpenSky does not provide weather data."""
        return []

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """OpenSky does not provide passenger demand data."""
        return 0.0

"""Iowa State Mesonet weather adapter.

Reads downloaded ASOS/METAR observation CSVs from the Iowa State Mesonet:
https://mesonet.agron.iastate.edu/request/download.phtml

Classifies each observation into CAVOK/VMC/IMC/LIFR using visibility and
ceiling height, and computes empirical weather state transition probabilities
for Monte Carlo planning scenarios.

Expected CSV columns (Iowa State Mesonet format):
    station, valid, tmpf, dwpf, relh, drct, sknt, vsby,
    skyc1, skyl1, skyc2, skyl2, ...
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from .base import AbstractAdapter

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]


def _classify_category(vsby: float, skyc1: str, skyl1: float) -> str:
    """Classify a single observation into ICAO flight category.

    Args:
        vsby: Visibility in statute miles.
        skyc1: Lowest sky cover type (CLR, FEW, SCT, BKN, OVC).
        skyl1: Lowest sky cover height in feet AGL.

    Returns:
        One of CAVOK, VMC, IMC, LIFR.
    """
    vis_m = vsby * 1609.34  # statute miles → metres
    has_ceiling = skyc1 in ("BKN", "OVC")
    ceil_ft = skyl1 if has_ceiling else 99999.0

    if vis_m > 10000 and ceil_ft > 5000:
        return "CAVOK"
    if vis_m > 5000 and ceil_ft > 1500:
        return "VMC"
    if vis_m > 1500 and ceil_ft > 500:
        return "IMC"
    return "LIFR"


class MesonetAdapter(AbstractAdapter):
    """Adapter reading Iowa State Mesonet ASOS observation CSVs."""

    def __init__(self, csv_path: str | Path):
        if pd is None:
            raise ImportError("pandas is required for Mesonet adapter: pip install pandas")

        self._csv_path = Path(csv_path)
        # Mesonet CSVs have a comment header — detect and skip
        self.df = self._load_csv()
        self._classify_categories()

    def _load_csv(self) -> "pd.DataFrame":
        """Load CSV, handling Mesonet's variable header format."""
        path = self._csv_path

        # Detect number of comment lines to skip
        skip_rows = 0
        with open(path) as f:
            for line in f:
                if line.startswith("#") or line.startswith("station"):
                    if line.startswith("station"):
                        break
                    skip_rows += 1
                else:
                    break

        df = pd.read_csv(path, skiprows=skip_rows, low_memory=False)
        df.columns = df.columns.str.strip().str.lower()

        # Parse timestamps
        if "valid" in df.columns:
            df["valid"] = pd.to_datetime(df["valid"], errors="coerce")
            df = df.dropna(subset=["valid"])

        # Clean numeric columns
        for col in ["vsby", "sknt", "skyl1", "skyl2", "tmpf", "dwpf"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Fill missing visibility with good default
        if "vsby" in df.columns:
            df["vsby"] = df["vsby"].fillna(10.0)
        if "skyl1" in df.columns:
            df["skyl1"] = df["skyl1"].fillna(99999.0)
        if "skyc1" in df.columns:
            df["skyc1"] = df["skyc1"].fillna("CLR")

        return df

    def _classify_categories(self) -> None:
        """Add 'category' column based on visibility and ceiling."""
        self.df["category"] = self.df.apply(
            lambda row: _classify_category(
                float(row.get("vsby", 10.0)),
                str(row.get("skyc1", "CLR")),
                float(row.get("skyl1", 99999.0)),
            ),
            axis=1,
        )

    @property
    def source_name(self) -> str:
        return f"Iowa State Mesonet ({self._csv_path.name})"

    @property
    def is_real_data(self) -> bool:
        return True

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        """Return hourly weather observations for the given date.

        Groups observations by hour and takes the first observation per hour.
        """
        day_data = self.df[self.df["valid"].dt.date == sim_date]
        if day_data.empty:
            return []

        # Group by hour, take first observation
        hourly: list[dict] = []
        for hour in range(24):
            hour_data = day_data[day_data["valid"].dt.hour == hour]
            if hour_data.empty:
                continue

            row = hour_data.iloc[0]
            hourly.append({
                "hour": hour,
                "category": str(row.get("category", "CAVOK")),
                "wind_speed_kt": round(float(row.get("sknt", 0)), 1),
                "visibility_m": round(float(row.get("vsby", 10.0)) * 1609.34, 0),
                "temperature_f": round(float(row.get("tmpf", 59)), 1),
            })

        return hourly

    def get_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Compute empirical weather state transition probabilities.

        Returns P(next_hour_state | current_hour_state) as a nested dict.
        Used to calibrate the simulation weather FSM with real data.
        """
        transitions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        categories = self.df["category"].tolist()

        for i in range(len(categories) - 1):
            transitions[categories[i]][categories[i + 1]] += 1

        # Normalise to probabilities
        matrix: dict[str, dict[str, float]] = {}
        for from_state, counts in transitions.items():
            total = sum(counts.values())
            if total > 0:
                matrix[from_state] = {k: round(v / total, 4) for k, v in counts.items()}

        return matrix

    def get_category_distribution(self) -> dict[str, float]:
        """Percentage of observations in each weather category."""
        counts = self.df["category"].value_counts(normalize=True)
        return {str(k): round(float(v), 4) for k, v in counts.items()}

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        """Mesonet does not provide flight schedules."""
        return []

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        """Mesonet does not provide passenger demand data."""
        return 0.0

    def get_date_range(self) -> tuple[date, date] | None:
        """Return the first and last date covered by the dataset."""
        if self.df.empty or "valid" not in self.df.columns:
            return None
        return (
            self.df["valid"].min().date(),
            self.df["valid"].max().date(),
        )

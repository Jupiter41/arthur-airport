"""Historical METAR data replay from IEM Mesonet CSV files.

Parses CSV files downloaded from Iowa Environmental Mesonet (IEM):
  https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py

CSV columns used:
  station, valid, tmpf, dwpf, drct, sknt, vsby, gust,
  skyc1, skyl1, wxcodes, alti, metar

Provides a time-indexed lookup so the weather service can replay
historical weather keyed on simulation time.
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

from services.parameters import WeatherParams

logger = logging.getLogger(__name__)

# Visibility conversion: statute miles → metres
SM_TO_M = 1609.34

# Temperature conversion: Fahrenheit → Celsius
def _f_to_c(f: float) -> float:
    return round((f - 32) * 5 / 9, 1)

# Altimeter (inHg) → QNH (hPa)
def _inhg_to_hpa(inhg: float) -> int:
    return round(inhg * 33.8639)


def _classify_category(visibility_m: float, ceiling_ft: float | None) -> str:
    """Classify IFR category from visibility and ceiling.

    CAVOK: vis > 10km and no significant ceiling
    VMC:   vis 5-10km or ceiling > 1500ft
    IMC:   vis 1.5-5km or ceiling 500-1500ft
    LIFR:  vis < 1.5km or ceiling < 500ft
    """
    if ceiling_ft is None:
        # No ceiling reported — use visibility only
        if visibility_m >= 10000:
            return "CAVOK"
        elif visibility_m >= 5000:
            return "VMC"
        elif visibility_m >= 1500:
            return "IMC"
        else:
            return "LIFR"

    # Both visibility and ceiling available
    if visibility_m >= 10000 and ceiling_ft >= 5000:
        return "CAVOK"
    elif visibility_m >= 5000 and ceiling_ft >= 1500:
        return "VMC"
    elif visibility_m >= 1500 and ceiling_ft >= 500:
        return "IMC"
    else:
        return "LIFR"


def _parse_float(val: str, default: float = 0.0) -> float:
    """Parse a float from CSV, returning default for 'M' (missing) or invalid."""
    if not val or val.strip() in ("M", ""):
        return default
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return default


def _parse_phenomena(wxcodes: str) -> list[str]:
    """Parse weather phenomena codes from IEM wxcodes field."""
    if not wxcodes or wxcodes.strip() in ("M", ""):
        return []
    return [p.strip() for p in wxcodes.strip().split(" ") if p.strip()]


def _parse_ceiling(skyc1: str, skyl1: str) -> int | None:
    """Extract ceiling from sky condition layer 1.

    skyc1: FEW/SCT/BKN/OVC/VV (sky cover code)
    skyl1: altitude in feet AGL
    """
    cover = (skyc1 or "").strip().upper()
    if cover in ("M", "", "CLR", "SKC"):
        return None
    # BKN and OVC represent a ceiling
    if cover in ("BKN", "OVC", "VV"):
        alt = _parse_float(skyl1, 0.0)
        return int(alt) if alt > 0 else None
    return None


class HistoricalMetarSource:
    """Loads historical METAR CSV and provides time-based lookups.

    On construction, reads the entire CSV into a sorted list of
    (datetime, WeatherParams, raw_metar) tuples. During simulation,
    the weather service calls `get_params_at(sim_time)` to get the
    observation closest to (but not after) the queried time.

    Time mapping: simulation days are mapped to historical days cyclically.
    If the CSV has 30 days of data and the sim runs past day 30, it wraps.
    """

    def __init__(self, csv_path: str | Path):
        self._observations: list[tuple[datetime, WeatherParams, str]] = []
        self._loaded = False
        self._csv_path = Path(csv_path)
        self._base_date: datetime | None = None

    def load(self) -> int:
        """Load CSV file. Returns number of observations loaded."""
        if not self._csv_path.exists():
            logger.warning("Historical METAR file not found: %s", self._csv_path)
            return 0

        observations: list[tuple[datetime, WeatherParams, str]] = []

        with self._csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    valid_str = (row.get("valid") or "").strip()
                    if not valid_str:
                        continue
                    obs_time = datetime.strptime(valid_str, "%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    continue

                tmpf = _parse_float(row.get("tmpf", ""), 59.0)
                dwpf = _parse_float(row.get("dwpf", ""), 50.0)
                drct = _parse_float(row.get("drct", ""), 0.0)
                sknt = _parse_float(row.get("sknt", ""), 0.0)
                vsby_sm = _parse_float(row.get("vsby", ""), 10.0)
                gust = _parse_float(row.get("gust", ""), 0.0)
                alti = _parse_float(row.get("alti", ""), 29.92)

                skyc1 = (row.get("skyc1") or "").strip()
                skyl1 = (row.get("skyl1") or "").strip()
                wxcodes = (row.get("wxcodes") or "").strip()
                metar_raw = (row.get("metar") or "").strip()

                visibility_m = int(vsby_sm * SM_TO_M)
                wind_direction = int(drct) % 360
                wind_speed_kt = int(sknt)
                wind_gust_kt = int(gust) if gust > 0 else 0
                ceiling_ft = _parse_ceiling(skyc1, skyl1)
                temperature_c = _f_to_c(tmpf)
                dew_point_c = _f_to_c(dwpf)
                qnh_hpa = _inhg_to_hpa(alti)
                phenomena = _parse_phenomena(wxcodes)

                category = _classify_category(float(visibility_m), ceiling_ft)

                params = WeatherParams(
                    category=category,
                    visibility_m=visibility_m,
                    wind_direction=wind_direction,
                    wind_speed_kt=wind_speed_kt,
                    wind_gust_kt=wind_gust_kt,
                    ceiling_ft=ceiling_ft,
                    temperature_c=temperature_c,
                    dew_point_c=dew_point_c,
                    qnh_hpa=qnh_hpa,
                    phenomena=phenomena,
                )

                observations.append((obs_time, params, metar_raw))

        observations.sort(key=lambda x: x[0])
        self._observations = observations
        self._loaded = bool(observations)

        if observations:
            self._base_date = observations[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
            span_days = (observations[-1][0] - observations[0][0]).days + 1
            logger.info(
                "Loaded %d historical METAR observations spanning %d days from %s",
                len(observations),
                span_days,
                self._csv_path.name,
            )
        else:
            logger.warning("No valid observations parsed from %s", self._csv_path)

        return len(observations)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    @property
    def span_days(self) -> int:
        if not self._observations:
            return 0
        return (self._observations[-1][0] - self._observations[0][0]).days + 1

    def get_params_at(self, sim_time: datetime) -> tuple[WeatherParams, str] | None:
        """Get historical weather params for the given simulation time.

        Maps sim_time to the historical record cyclically:
        - sim day 1 maps to first day in CSV, etc.
        - Wraps around when sim_time exceeds the CSV span.

        Returns (WeatherParams, raw_metar_string) or None if no data.
        """
        if not self._loaded or not self._observations or not self._base_date:
            return None

        # Map sim_time to historical time
        span = self.span_days
        sim_start = sim_time.replace(hour=0, minute=0, second=0, microsecond=0)
        # Use the time-of-day from sim_time, mapped to a day in the historical range
        day_offset = (sim_start - self._base_date).days % span
        mapped_time = self._base_date + timedelta(days=day_offset)
        mapped_time = mapped_time.replace(
            hour=sim_time.hour,
            minute=sim_time.minute,
            second=0,
            microsecond=0,
        )

        # Binary search for the closest observation <= mapped_time
        lo, hi = 0, len(self._observations) - 1
        result_idx = 0

        while lo <= hi:
            mid = (lo + hi) // 2
            if self._observations[mid][0] <= mapped_time:
                result_idx = mid
                lo = mid + 1
            else:
                hi = mid - 1

        _, params, raw_metar = self._observations[result_idx]

        # Rewrite the METAR station and time to match our airport
        return params, raw_metar

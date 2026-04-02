"""Live METAR fetcher from Aviation Weather Center API.

Fetches real-time METAR data from the public US government API:
  https://aviationweather.gov/api/data/metar

No API key required. Updates are cached for 30 real minutes.
Falls back to None on any failure — the caller should use the FSM.
"""

import logging
import time

import httpx

from services.parameters import WeatherParams

logger = logging.getLogger(__name__)

_METAR_API = "https://aviationweather.gov/api/data/metar"
_CACHE_TTL_SECONDS = 1800  # 30 minutes real time


def _classify_category(visibility_m: float, ceiling_ft: float | None) -> str:
    """Classify IFR category from visibility and ceiling."""
    if ceiling_ft is None:
        if visibility_m >= 10000:
            return "CAVOK"
        elif visibility_m >= 5000:
            return "VMC"
        elif visibility_m >= 1500:
            return "IMC"
        else:
            return "LIFR"

    if visibility_m >= 10000 and ceiling_ft >= 5000:
        return "CAVOK"
    elif visibility_m >= 5000 and ceiling_ft >= 1500:
        return "VMC"
    elif visibility_m >= 1500 and ceiling_ft >= 500:
        return "IMC"
    else:
        return "LIFR"


def _parse_metar_json(data: dict) -> tuple[WeatherParams, str] | None:
    """Parse a single METAR JSON object from Aviation Weather Center API.

    The API returns objects like:
    {
        "icaoId": "EGLL",
        "rawOb": "EGLL 010920Z ...",
        "temp": 8.0,
        "dewp": 6.0,
        "wdir": 270,
        "wspd": 12,
        "wgst": null,
        "visib": "9999",
        "altim": 1013.0,
        "clouds": [{"cover": "BKN", "base": 1200}],
        "wxString": "RA",
        ...
    }
    """
    try:
        raw_metar = data.get("rawOb", "")

        temp_c = float(data.get("temp", 15))
        dewp_c = float(data.get("dewp", 10))
        wdir = int(data.get("wdir", 0)) % 360
        wspd = int(data.get("wspd", 0))
        wgst = int(data["wgst"]) if data.get("wgst") is not None else 0

        # Visibility: can be "9999" or a numeric
        vis_raw = data.get("visib", "9999")
        try:
            vis_m = int(float(str(vis_raw)))
        except (ValueError, TypeError):
            vis_m = 9999

        # Altimeter: hPa
        altim = data.get("altim", 1013)
        qnh_hpa = int(float(altim)) if altim else 1013

        # Clouds → ceiling
        ceiling_ft = None
        clouds = data.get("clouds", [])
        if isinstance(clouds, list):
            for cloud in clouds:
                cover = (cloud.get("cover") or "").upper()
                base = cloud.get("base")
                if cover in ("BKN", "OVC", "VV") and base is not None:
                    ceiling_ft = int(base)
                    break

        # Weather phenomena
        wx = data.get("wxString", "")
        phenomena = [p.strip() for p in (wx or "").split() if p.strip()] if wx else []

        category = _classify_category(float(vis_m), ceiling_ft)

        params = WeatherParams(
            category=category,
            visibility_m=vis_m,
            wind_direction=wdir,
            wind_speed_kt=wspd,
            wind_gust_kt=wgst,
            ceiling_ft=ceiling_ft,
            temperature_c=round(temp_c, 1),
            dew_point_c=round(dewp_c, 1),
            qnh_hpa=qnh_hpa,
            phenomena=phenomena,
        )

        return params, raw_metar

    except Exception as e:
        logger.warning("Failed to parse METAR JSON: %s", e)
        return None


class LiveMetarSource:
    """Fetches live METAR from Aviation Weather Center.

    Caches for 30 real minutes. Thread-safe for single-writer usage.
    Falls back to None on any network/parse error.
    """

    def __init__(self, icao: str = "EGLL"):
        self._icao = icao.upper()
        self._cache: tuple[WeatherParams, str] | None = None
        self._cache_time: float = 0.0

    @property
    def icao(self) -> str:
        return self._icao

    def fetch(self) -> tuple[WeatherParams, str] | None:
        """Fetch the latest METAR. Returns cached if fresh enough.

        Returns (WeatherParams, raw_metar) or None on failure.
        """
        now = time.monotonic()
        if self._cache and (now - self._cache_time) < _CACHE_TTL_SECONDS:
            return self._cache

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    _METAR_API,
                    params={"ids": self._icao, "format": "json"},
                )
                resp.raise_for_status()
                data = resp.json()

            if not data or not isinstance(data, list):
                logger.warning("Empty or invalid METAR response for %s", self._icao)
                return self._cache  # return stale cache

            result = _parse_metar_json(data[0])
            if result:
                self._cache = result
                self._cache_time = now
                logger.info(
                    "Live METAR fetched for %s: %s (category=%s)",
                    self._icao,
                    result[1][:60],
                    result[0].category,
                )
            return result

        except Exception as e:
            logger.warning("Failed to fetch live METAR for %s: %s", self._icao, e)
            return self._cache  # return stale cache on failure

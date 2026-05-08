"""ADS-B live data integration via adsb.lol community API.

Polls the adsb.lol `/v2/lat/{lat}/lon/{lon}/dist/{dist}` endpoint,
caching state vectors for aircraft within 400 km of KART (49.6233°N,
6.2044°E — Luxembourg).

Fallback: OpenSky Network `/api/states/all` (rate-limited, optional auth).
No Redis needed — scope is small (< 2000 aircraft at most).
"""

import asyncio
import logging
import math
import os
import time
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# KART coordinates — positioned at Luxembourg Findel (ELLX) for ADS-B coverage
KART_LAT = 49.6233
KART_LON = 6.2044
RADIUS_KM = 400

# OpenSky bounding box — rough box covering KART ± margin to encompass radius
# 1° latitude ≈ 111 km.  At 49.6°N, 1° longitude ≈ 72 km.
_LAT_MARGIN = RADIUS_KM / 111.0
_LON_MARGIN = RADIUS_KM / (111.0 * math.cos(math.radians(KART_LAT)))
BBOX = {
    "lamin": KART_LAT - _LAT_MARGIN,
    "lamax": KART_LAT + _LAT_MARGIN,
    "lomin": KART_LON - _LON_MARGIN,
    "lomax": KART_LON + _LON_MARGIN,
}

# Primary: adsb.lol — free community API, no auth, no rate limits
ADSB_LOL_URL = f"https://api.adsb.lol/v2/lat/{KART_LAT}/lon/{KART_LON}/dist/{RADIUS_KM}"

# Fallback: OpenSky Network — heavily rate-limited for anonymous users
OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

POLL_INTERVAL_SEC = int(os.getenv("ADSB_POLL_INTERVAL_SEC", "30"))
BACKOFF_BASE_SEC = 60
BACKOFF_MAX_SEC = 600
MAX_CONSECUTIVE_ERRORS = 5

EARTH_RADIUS_KM = 6371.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ADSBCache:
    """Thread-safe in-memory cache for ADS-B state vectors."""

    def __init__(self) -> None:
        self._states: list[dict[str, Any]] = []
        self._last_update: float = 0.0
        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._consecutive_errors: int = 0
        self._use_synthetic: bool = False
        self._source: str = "adsb.lol"
        self._auth: tuple[str, str] | None = None
        if OPENSKY_USERNAME and OPENSKY_PASSWORD:
            self._auth = (OPENSKY_USERNAME, OPENSKY_PASSWORD)
            logger.info("OpenSky credentials configured — using authenticated requests")

    @property
    def states(self) -> list[dict[str, Any]]:
        return list(self._states)

    @property
    def last_update_iso(self) -> str | None:
        if self._last_update == 0.0:
            return None
        return datetime.utcfromtimestamp(self._last_update).isoformat() + "Z"

    @property
    def count(self) -> int:
        return len(self._states)

    async def poll_once(self) -> int:
        """Poll ADS-B API and update the cache. Returns count of aircraft.

        Tries adsb.lol first (free, no auth). Falls back to OpenSky if that fails.
        After MAX_CONSECUTIVE_ERRORS total failures, switches to synthetic mode.
        """
        if self._use_synthetic:
            return len(self._states)

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)

        # --- Try adsb.lol first ---
        try:
            resp = await self._client.get(ADSB_LOL_URL)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_adsb_lol(data)
        except Exception as e:
            logger.debug("adsb.lol poll failed: %s — trying OpenSky fallback", e)

        # --- Fallback: OpenSky ---
        params = {
            "lamin": BBOX["lamin"],
            "lamax": BBOX["lamax"],
            "lomin": BBOX["lomin"],
            "lomax": BBOX["lomax"],
        }
        try:
            kwargs: dict[str, Any] = {"params": params}
            if self._auth:
                kwargs["auth"] = self._auth
            resp = await self._client.get(OPENSKY_URL, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_opensky(data)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "ADS-B APIs failed %d times consecutively — switching to synthetic fallback",
                    self._consecutive_errors,
                )
                self._use_synthetic = True
                return len(self._states)
            if status == 429:
                backoff = min(
                    BACKOFF_BASE_SEC * (2 ** (self._consecutive_errors - 1)),
                    BACKOFF_MAX_SEC,
                )
                logger.warning(
                    "OpenSky API rate limited (429), backing off %ds (attempt %d/%d)",
                    backoff,
                    self._consecutive_errors,
                    MAX_CONSECUTIVE_ERRORS,
                )
                await asyncio.sleep(backoff)
            else:
                logger.warning("OpenSky API error: %s", status)
            return len(self._states)
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "ADS-B APIs failed %d times — switching to synthetic fallback",
                    self._consecutive_errors,
                )
                self._use_synthetic = True
                return len(self._states)
            logger.warning("OpenSky poll failed: %s", e)
            return len(self._states)

    def _parse_adsb_lol(self, data: dict) -> int:
        """Parse adsb.lol v2 response format."""
        self._consecutive_errors = 0
        raw = data.get("ac") or []
        filtered: list[dict[str, Any]] = []
        for ac in raw:
            lat = ac.get("lat")
            lon = ac.get("lon")
            if lat is None or lon is None:
                continue
            alt_baro = ac.get("alt_baro")
            if alt_baro == "ground":
                alt_baro = 0
            callsign = (ac.get("flight") or "").strip()
            dist = ac.get("dst")
            if dist is None:
                dist = _haversine(KART_LAT, KART_LON, lat, lon)
            if dist > RADIUS_KM:
                continue
            filtered.append({
                "icao24": ac.get("hex", ""),
                "callsign": callsign,
                "origin_country": "",
                "latitude": lat,
                "longitude": lon,
                "altitude_m": (alt_baro or 0) * 0.3048 if isinstance(alt_baro, (int, float)) else None,
                "on_ground": alt_baro == 0 or ac.get("alt_baro") == "ground",
                "velocity_ms": (ac.get("gs") or 0) * 0.5144 if ac.get("gs") else None,
                "heading": ac.get("track"),
                "vertical_rate": ac.get("geom_rate"),
                "distance_km": round(dist, 1) if isinstance(dist, (int, float)) else None,
            })
        self._states = filtered
        self._last_update = time.time()
        self._source = "adsb.lol"
        logger.info("ADS-B poll (adsb.lol): %d aircraft within %d km of KART", len(filtered), RADIUS_KM)
        return len(filtered)

    def _parse_opensky(self, data: dict) -> int:
        """Parse OpenSky Network response format."""
        self._consecutive_errors = 0
        raw_states = data.get("states") or []
        filtered: list[dict[str, Any]] = []
        for sv in raw_states:
            lat = sv[6]
            lon = sv[5]
            if lat is None or lon is None:
                continue
            dist = _haversine(KART_LAT, KART_LON, lat, lon)
            if dist > RADIUS_KM:
                continue
            callsign = (sv[1] or "").strip()
            filtered.append({
                "icao24": sv[0],
                "callsign": callsign,
                "origin_country": sv[2],
                "latitude": lat,
                "longitude": lon,
                "altitude_m": sv[7] or sv[13],
                "on_ground": sv[8],
                "velocity_ms": sv[9],
                "heading": sv[10],
                "vertical_rate": sv[11],
                "distance_km": round(dist, 1),
            })
        self._states = filtered
        self._last_update = time.time()
        self._source = "opensky"
        logger.info("ADS-B poll (OpenSky): %d aircraft within %d km of KART", len(filtered), RADIUS_KM)
        return len(filtered)

    async def start_polling(self) -> None:
        """Start background polling loop."""
        if self._running:
            return
        self._running = True
        logger.info("ADS-B polling started (interval=%ds, radius=%dkm)", POLL_INTERVAL_SEC, RADIUS_KM)
        while self._running:
            if self._use_synthetic:
                # Refresh synthetic positions from active flights
                try:
                    from services.adsb_synthetic import generate_synthetic_adsb
                    states = await generate_synthetic_adsb()
                    self.set_synthetic_states(states)
                except Exception as e:
                    logger.warning("Synthetic ADS-B generation failed: %s", e)
            else:
                await self.poll_once()
            await asyncio.sleep(POLL_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False
        if self._client:
            asyncio.ensure_future(self._client.aclose())
            self._client = None

    def set_synthetic_states(self, states: list[dict[str, Any]]) -> None:
        """Replace cache with synthetic ADS-B data derived from simulated flights.

        Called by the flight-service when OpenSky is unavailable and synthetic
        fallback is active.
        """
        self._states = states
        self._last_update = time.time()
        logger.debug("Synthetic ADS-B: %d aircraft injected", len(states))

    def to_geojson(self) -> dict:
        """Return current states as GeoJSON FeatureCollection."""
        features = []
        for s in self._states:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [s["longitude"], s["latitude"]],
                },
                "properties": {
                    "icao24": s["icao24"],
                    "callsign": s["callsign"],
                    "origin_country": s["origin_country"],
                    "altitude_m": s["altitude_m"],
                    "on_ground": s["on_ground"],
                    "velocity_ms": s["velocity_ms"],
                    "heading": s["heading"],
                    "vertical_rate": s["vertical_rate"],
                    "distance_km": s["distance_km"],
                },
            })
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "center": {"lat": KART_LAT, "lon": KART_LON},
                "radius_km": RADIUS_KM,
                "aircraft_count": len(features),
                "last_update": self.last_update_iso,
                "source": "synthetic" if self._use_synthetic else self._source,
            },
        }


# Module-level singleton
_cache = ADSBCache()


def get_adsb_cache() -> ADSBCache:
    return _cache

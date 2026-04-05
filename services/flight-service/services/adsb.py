"""ADS-B live data integration via OpenSky Network REST API.

Polls the OpenSky `/api/states/all` endpoint every 10 real seconds, caching
state vectors for aircraft within 1000 km of KART (38.75°N, -27.0833°W).
No Redis needed — scope is small (< 500 aircraft at most).
"""

import asyncio
import logging
import math
import time
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# KART coordinates (from dashboard geospatial.ts)
KART_LAT = 38.75
KART_LON = -27.0833
RADIUS_KM = 1000

# OpenSky bounding box — rough box covering KART ± ~9° to encompass 1000 km
# 1° latitude ≈ 111 km.  At 38.75°N, 1° longitude ≈ 87 km.
_LAT_MARGIN = RADIUS_KM / 111.0                      # ~9.0°
_LON_MARGIN = RADIUS_KM / (111.0 * math.cos(math.radians(KART_LAT)))  # ~11.5°
BBOX = {
    "lamin": KART_LAT - _LAT_MARGIN,
    "lamax": KART_LAT + _LAT_MARGIN,
    "lomin": KART_LON - _LON_MARGIN,
    "lomax": KART_LON + _LON_MARGIN,
}

OPENSKY_URL = "https://opensky-network.org/api/states/all"
POLL_INTERVAL_SEC = 10

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
        """Poll OpenSky API once and update the cache. Returns count of aircraft."""
        params = {
            "lamin": BBOX["lamin"],
            "lamax": BBOX["lamax"],
            "lomin": BBOX["lomin"],
            "lomax": BBOX["lomax"],
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(OPENSKY_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            # 429 rate limit is common on free tier
            logger.warning("OpenSky API error: %s", e.response.status_code)
            return len(self._states)
        except Exception as e:
            logger.warning("OpenSky poll failed: %s", e)
            return len(self._states)

        raw_states = data.get("states") or []
        filtered: list[dict[str, Any]] = []
        for sv in raw_states:
            # OpenSky state vector indices:
            # 0=icao24, 1=callsign, 2=origin_country, 3=time_position, 4=last_contact,
            # 5=longitude, 6=latitude, 7=baro_altitude, 8=on_ground, 9=velocity,
            # 10=true_track, 11=vertical_rate, 12=sensors, 13=geo_altitude,
            # 14=squawk, 15=spi, 16=position_source
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
        logger.debug("ADS-B poll: %d aircraft within %d km of KART", len(filtered), RADIUS_KM)
        return len(filtered)

    async def start_polling(self) -> None:
        """Start background polling loop."""
        if self._running:
            return
        self._running = True
        logger.info("ADS-B polling started (interval=%ds, radius=%dkm)", POLL_INTERVAL_SEC, RADIUS_KM)
        while self._running:
            await self.poll_once()
            await asyncio.sleep(POLL_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False

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
            },
        }


# Module-level singleton
_cache = ADSBCache()


def get_adsb_cache() -> ADSBCache:
    return _cache

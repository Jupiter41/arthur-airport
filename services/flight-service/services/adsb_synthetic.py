"""Synthetic ADS-B data generator — fallback when OpenSky is unavailable.

Produces ADS-B-like state vectors from simulated flights currently airborne,
so the dashboard's ADS-B overlay shows aircraft even without a live data feed.
"""

import logging
import math
import random

from db.neo4j import get_driver
from services.adsb import KART_LAT, KART_LON, RADIUS_KM, _haversine

logger = logging.getLogger(__name__)

# Approximate destination coordinates for synthetic position computation
# This is a subset — unknown destinations get a random bearing
_DEST_COORDS: dict[str, tuple[float, float]] = {
    "CDG": (49.0097, 2.5479),
    "LHR": (51.4700, -0.4543),
    "FRA": (50.0379, 8.5622),
    "AMS": (52.3086, 4.7639),
    "BCN": (41.2971, 2.0785),
    "FCO": (41.8003, 12.2389),
    "MAD": (40.4936, -3.5668),
    "IST": (41.2753, 28.7519),
    "JFK": (40.6413, -73.7781),
    "DXB": (25.2532, 55.3657),
    "ZRH": (47.4647, 8.5492),
    "BRU": (50.9014, 4.4844),
    "VIE": (48.1103, 16.5697),
    "MUC": (48.3538, 11.7861),
    "CPH": (55.6181, 12.6560),
    "OSL": (60.1976, 11.1004),
    "ARN": (59.6519, 17.9186),
    "HEL": (60.3172, 24.9633),
    "WAW": (52.1657, 20.9671),
    "PRG": (50.1008, 14.2600),
    "ATH": (37.9364, 23.9445),
    "LIS": (38.7813, -9.1359),
}


def _interpolate_position(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    progress: float,
) -> tuple[float, float, float]:
    """Linearly interpolate lat/lon and compute heading."""
    lat = origin_lat + (dest_lat - origin_lat) * progress
    lon = origin_lon + (dest_lon - origin_lon) * progress
    # Compute heading
    dlon = math.radians(dest_lon - lon)
    y = math.sin(dlon) * math.cos(math.radians(dest_lat))
    x = math.cos(math.radians(lat)) * math.sin(math.radians(dest_lat)) - math.sin(
        math.radians(lat)
    ) * math.cos(math.radians(dest_lat)) * math.cos(dlon)
    heading = (math.degrees(math.atan2(y, x)) + 360) % 360
    return lat, lon, heading


async def generate_synthetic_adsb() -> list[dict]:
    """Query Neo4j for airborne flights and generate synthetic ADS-B states."""
    driver = get_driver()
    if driver is None:
        return []

    query = """
    MATCH (f:Flight)
    WHERE f.status IN ['departed', 'airborne', 'approach']
    RETURN f.id AS id, f.flight_number AS flight_number,
           f.direction AS direction, f.destination_iata AS dest,
           f.origin_iata AS origin, f.status AS status,
           f.aircraft_registration AS reg,
           f.scheduled_departure AS sched_dep,
           f.estimated_arrival AS est_arr,
           f.flight_duration_minutes AS duration_min
    """
    states = []
    async with driver.session() as session:
        result = await session.run(query)
        records = await result.data()

    for rec in records:
        dest = rec.get("dest", "")
        origin = rec.get("origin", "")
        direction = rec.get("direction", "departure")
        status = rec.get("status", "airborne")

        # Determine origin/destination coordinates
        if direction == "departure":
            o_lat, o_lon = KART_LAT, KART_LON
            d_coords = _DEST_COORDS.get(dest)
            if not d_coords:
                # Random point within radius
                angle = random.uniform(0, 2 * math.pi)
                d_lat = KART_LAT + (RADIUS_KM / 111) * math.cos(angle) * 0.7
                d_lon = KART_LON + (RADIUS_KM / (111 * math.cos(math.radians(KART_LAT)))) * math.sin(angle) * 0.7
                d_coords = (d_lat, d_lon)
        else:
            d_lat_dest, d_lon_dest = KART_LAT, KART_LON
            o_coords = _DEST_COORDS.get(origin)
            if not o_coords:
                angle = random.uniform(0, 2 * math.pi)
                o_lat_o = KART_LAT + (RADIUS_KM / 111) * math.cos(angle) * 0.7
                o_lon_o = KART_LON + (RADIUS_KM / (111 * math.cos(math.radians(KART_LAT)))) * math.sin(angle) * 0.7
                o_coords = (o_lat_o, o_lon_o)
            o_lat, o_lon = o_coords
            d_coords = (d_lat_dest, d_lon_dest)

        d_lat, d_lon = d_coords

        # Estimate progress based on status
        if status == "departed":
            progress = random.uniform(0.05, 0.25)
        elif status == "approach":
            progress = random.uniform(0.75, 0.95)
        else:
            progress = random.uniform(0.2, 0.8)

        lat, lon, heading = _interpolate_position(o_lat, o_lon, d_lat, d_lon, progress)

        # Only include if within radius
        dist = _haversine(KART_LAT, KART_LON, lat, lon)
        if dist > RADIUS_KM:
            continue

        callsign = (rec.get("flight_number") or "").replace("-", "").ljust(8)[:8]
        altitude = random.uniform(8000, 12000) if status == "airborne" else random.uniform(2000, 6000)

        states.append({
            "icao24": f"syn{rec['id'][:6]}",
            "callsign": callsign.strip(),
            "origin_country": "Synthetic",
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "altitude_m": round(altitude),
            "on_ground": False,
            "velocity_ms": random.uniform(180, 260),
            "heading": round(heading, 1),
            "vertical_rate": 0.0 if status == "airborne" else (-5.0 if status == "approach" else 8.0),
            "distance_km": round(dist, 1),
        })

    logger.info("Generated %d synthetic ADS-B states from active flights", len(states))
    return states

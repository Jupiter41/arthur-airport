"""REST endpoints for weather-service."""

import logging
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import PlainTextResponse

from db.neo4j import get_current_weather, get_weather_history
from kafka.consumer import get_current_state
from services.capacity import compute_runway_capacity, compute_impact_summary
from services.parameters import WeatherParams
from services.metar import build_metar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get("/weather/current")
async def current_weather():
    """Current weather conditions at KART."""
    state = get_current_state()
    params = state.get("params")
    state.get("sim_time")

    if params is None:
        raise HTTPException(status_code=503, detail="Weather state not yet initialized")

    # Read from Neo4j (source of truth)
    weather = await get_current_weather()
    if weather is None:
        raise HTTPException(status_code=503, detail="No weather state in Neo4j")

    # Reconstruct params for capacity calculation
    p = WeatherParams(
        category=weather["category"],
        visibility_m=weather["visibility_m"],
        wind_direction=weather["wind_direction"],
        wind_speed_kt=weather["wind_speed_kt"],
        wind_gust_kt=weather["wind_gust_kt"],
        ceiling_ft=weather["ceiling_ft"],
        temperature_c=weather["temperature_c"],
        dew_point_c=weather["dew_point_c"],
        qnh_hpa=weather["qnh_hpa"],
        phenomena=weather["phenomena"],
    )
    capacity = compute_runway_capacity(p)
    ts = datetime.fromisoformat(weather["timestamp"])
    metar_raw = build_metar(p, ts)

    return {
        "id": weather["id"],
        "sim_time": weather["timestamp"],
        "category": weather["category"],
        "visibility_m": weather["visibility_m"],
        "wind_direction": weather["wind_direction"],
        "wind_speed_kt": weather["wind_speed_kt"],
        "wind_gust_kt": weather["wind_gust_kt"],
        "ceiling_ft": weather["ceiling_ft"],
        "temperature_c": weather["temperature_c"],
        "dew_point_c": weather["dew_point_c"],
        "qnh_hpa": weather["qnh_hpa"],
        "phenomena": weather["phenomena"],
        "runway_impact": {
            "category": capacity["runway_impact"],
            "arrival_rate": capacity["arrival_rate"],
            "departure_rate": capacity["departure_rate"],
            "active_runway": capacity["active_runway"],
            "ils_required": capacity["ils_required"],
        },
        "metar_raw": metar_raw,
    }


@router.get("/weather/metar", response_class=PlainTextResponse)
async def get_metar():
    """Latest METAR string (plain text)."""
    state = get_current_state()
    metar = state.get("metar")
    if not metar:
        raise HTTPException(status_code=503, detail="METAR not yet available")
    return metar


@router.get("/weather/taf", response_class=PlainTextResponse)
async def get_taf():
    """Current TAF (plain text)."""
    state = get_current_state()
    taf = state.get("taf")
    if not taf:
        raise HTTPException(status_code=503, detail="TAF not yet available")
    return taf


@router.get("/weather/history")
async def weather_history(hours: int = Query(default=12, ge=1, le=48)):
    """Rolling weather history for the last N simulated hours."""
    raw_states = await get_weather_history(hours=hours)

    if not raw_states:
        return {"from": None, "to": None, "states": []}

    # Build duration-based history entries
    states = []
    for i, s in enumerate(raw_states):
        from_time = s["timestamp"]
        if i + 1 < len(raw_states):
            to_time = raw_states[i + 1]["timestamp"]
        else:
            # Current state — still active
            current = get_current_state()
            to_time = current["sim_time"].isoformat() if current["sim_time"] else from_time

        from_dt = datetime.fromisoformat(from_time)
        to_dt = datetime.fromisoformat(to_time)
        duration_minutes = int((to_dt - from_dt).total_seconds() / 60)

        states.append({
            "category": s["category"],
            "previous_category": s.get("previous_category"),
            "from": from_time,
            "to": to_time,
            "duration_minutes": max(0, duration_minutes),
        })

    return {
        "from": raw_states[0]["timestamp"],
        "to": states[-1]["to"] if states else None,
        "states": states,
    }


@router.get("/weather/impact")
async def weather_impact():
    """Current operational impact summary."""
    weather = await get_current_weather()
    if weather is None:
        raise HTTPException(status_code=503, detail="No weather state available")

    p = WeatherParams(
        category=weather["category"],
        visibility_m=weather["visibility_m"],
        wind_direction=weather["wind_direction"],
        wind_speed_kt=weather["wind_speed_kt"],
        wind_gust_kt=weather["wind_gust_kt"],
        ceiling_ft=weather["ceiling_ft"],
        temperature_c=weather["temperature_c"],
        dew_point_c=weather["dew_point_c"],
        qnh_hpa=weather["qnh_hpa"],
        phenomena=weather["phenomena"],
    )
    capacity = compute_runway_capacity(p)
    impact = compute_impact_summary(p, capacity)
    return impact

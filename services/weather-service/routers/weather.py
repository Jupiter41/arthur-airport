"""REST endpoints for weather-service."""

import logging
import os
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
    metar_raw = build_metar(p, ts, weather.get("airport_icao") or "KART")

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
        "weather_source": os.getenv("WEATHER_SOURCE", "simulated"),
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

        # Strip timezone info to avoid offset-naive vs offset-aware mismatch
        # (Neo4j toString(datetime) and in-memory sim_time may differ)
        from_dt = datetime.fromisoformat(from_time).replace(tzinfo=None)
        to_dt = datetime.fromisoformat(to_time).replace(tzinfo=None)
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


@router.get("/weather/source")
async def weather_source():
    """Current weather data source configuration."""
    from kafka.consumer import get_current_state, get_weather_source
    source = get_weather_source()
    current = get_current_state()
    info: dict = {"source": source, "current_category": current.get("category")}

    if source == "historical":
        info["file"] = os.getenv("WEATHER_HISTORY_FILE", "/app/data/weather/EGLL_30days.csv")
    elif source == "live":
        info["icao"] = os.getenv("WEATHER_LIVE_ICAO", "EGLL")
        info["api"] = "https://aviationweather.gov/api/data/metar"

    return info


@router.get("/weather/compare")
async def compare_weather_sources():
    """Read-only comparison of all weather sources at the current sim time.

    Returns the current parameters from each available source (simulated,
    historical, live) without changing the active source. Useful for showing
    divergence across data providers.
    """
    import asyncio as _asyncio
    from kafka.consumer import get_current_state
    from services.parameters import sample_params

    state = get_current_state()
    sim_time = state.get("sim_time")
    current_category = state.get("category", "VMC")

    compare_fields = [
        "category", "visibility_m", "wind_speed_kt", "wind_direction",
        "wind_gust_kt", "ceiling_ft", "temperature_c", "dew_point_c", "qnh_hpa",
    ]

    def _params_to_dict(p) -> dict:
        return {f: getattr(p, f, None) for f in compare_fields}

    results: dict = {"sim_time": sim_time.isoformat() if sim_time else None, "sources": {}}

    # 1. Simulated (FSM) — show current state (always available)
    results["sources"]["simulated"] = {
        "available": True,
        **_params_to_dict(state.get("params", sample_params(current_category))),
    }

    # 2. Historical — try to read from the CSV without switching source
    from services.historical import HistoricalMetarSource
    hist_path = os.getenv("WEATHER_HISTORY_FILE", "/app/data/weather/EGLL_30days.csv")
    try:
        hist = HistoricalMetarSource(hist_path)
        count = hist.load()
        if count > 0 and sim_time:
            result = hist.get_params_at(sim_time)
            if result:
                params, raw = result
                results["sources"]["historical"] = {"available": True, **_params_to_dict(params)}
            else:
                results["sources"]["historical"] = {"available": False, "reason": "No data for current time"}
        else:
            results["sources"]["historical"] = {"available": False, "reason": "No observations loaded"}
    except Exception as e:
        results["sources"]["historical"] = {"available": False, "reason": str(e)}

    # 3. Live — fetch from ADDS API without blocking too long
    from services.live_metar import LiveMetarSource
    live_icao = os.getenv("WEATHER_LIVE_ICAO", "EGLL")
    try:
        live_src = LiveMetarSource(live_icao)
        loop = _asyncio.get_event_loop()
        live_result = await loop.run_in_executor(None, live_src.fetch)
        if live_result:
            params, raw = live_result
            results["sources"]["live"] = {"available": True, "icao": live_icao, **_params_to_dict(params)}
        else:
            results["sources"]["live"] = {"available": False, "reason": "ADDS API returned no data"}
    except Exception as e:
        results["sources"]["live"] = {"available": False, "reason": str(e)}

    return results


@router.post("/weather/source")
async def switch_weather_source_endpoint(body: dict):
    """Switch weather source at runtime.

    Body: { "source": "simulated"|"historical"|"live", "csv_path": ..., "live_icao": ... }
    """
    from kafka.consumer import switch_weather_source

    source = body.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="'source' field required")

    try:
        result = switch_weather_source(
            source=source,
            csv_path=body.get("csv_path"),
            live_icao=body.get("live_icao"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/weather/overrides")
async def get_overrides():
    """Get current weather parameter overrides."""
    from kafka.consumer import get_weather_overrides
    return {"overrides": get_weather_overrides()}


@router.post("/weather/overrides")
async def set_overrides(body: dict):
    """Set weather parameter overrides.

    Body: { "visibility_m": 5000, "wind_speed_kt": 25, ... }
    Set any value to null to unlock that parameter.
    """
    from kafka.consumer import set_weather_overrides
    result = set_weather_overrides(body)
    return {"overrides": result}

"""REST API router for passenger-service.

Base path: /api/v1
"""

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.neo4j import (
    get_all_passengers,
    get_passenger_by_id,
    search_passengers,
    get_status_counts,
)
from kafka.consumer import (
    get_sim_time,
    get_security,
    get_alerts as get_alerts_store,
    get_at_risk_connections,
)
from ml.features import build_features
from ml.inference import is_model_trained, predict, get_feature_importance
from services.zones import get_heatmap_zones

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get("/passengers")
async def list_passengers(
    flight_id: Optional[str] = Query(None),
    flight_number: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Comma-separated status filter"),
    zone: Optional[str] = Query(None),
    connection: Optional[bool] = Query(None),
    special_assistance: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = await get_all_passengers(
        flight_id=flight_id,
        flight_number=flight_number,
        status=status,
        zone=zone,
        connection=connection,
        special_assistance=special_assistance,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "passengers": items,
    }


@router.get("/passengers/search")
async def search_passengers_endpoint(
    pnr: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
):
    if not pnr and not name:
        raise HTTPException(status_code=400, detail="Provide pnr or name parameter")
    results = await search_passengers(pnr=pnr, name=name)
    return {"results": results}


# ── Source management ───────────────────────────────────────

@router.get("/passengers/source")
async def passenger_source():
    """Current passenger data source configuration."""
    from kafka.consumer import get_passenger_source_info
    return get_passenger_source_info()


@router.get("/passengers/compare")
async def passenger_compare():
    """Side-by-side comparison of simulated vs BTS historical passenger data."""
    from kafka.consumer import _ensure_bts_adapter

    sim_time = get_sim_time()
    by_status = await get_status_counts()

    active = {"checked_in", "security_queue", "airside", "at_gate",
              "deplaning", "baggage_claim"}
    sim_total = sum(v for k, v in by_status.items() if k in active)

    result: dict = {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "simulated": {
            "total_passengers": sim_total,
            "by_status": by_status,
        },
        "bts_historical": None,
        "deltas": None,
    }

    try:
        adapter = _ensure_bts_adapter()
        if sim_time:
            flow = adapter.get_flow_at(sim_time)
            bts_data = {
                "total_passengers": flow.total_passengers,
                "departing_passengers": flow.departing_passengers,
                "arriving_passengers": flow.arriving_passengers,
                "avg_load_factor": flow.avg_load_factor,
                "zone_counts": flow.zone_counts,
                "route_breakdown": flow.route_breakdown[:5],
            }
            result["bts_historical"] = bts_data
            result["deltas"] = {
                "total_passengers": sim_total - flow.total_passengers,
                "pct_difference": round(
                    ((sim_total - flow.total_passengers) / max(flow.total_passengers, 1)) * 100, 1
                ),
            }
        summary = adapter.get_summary()
        result["bts_summary"] = summary
    except Exception:
        logger.debug("BTS adapter not available for comparison", exc_info=True)

    return result


@router.post("/passengers/source")
async def switch_passenger_source_endpoint(body: dict):
    """Switch passenger source at runtime."""
    new_source = body.get("source")
    if new_source not in ("simulation", "bts_historical"):
        raise HTTPException(status_code=400, detail="source must be 'simulation' or 'bts_historical'")
    csv_path = body.get("csv_path")
    from kafka.consumer import switch_passenger_source
    result = switch_passenger_source(new_source, csv_path)
    return result


@router.get("/passengers/bts/flow")
async def bts_flow():
    """Get BTS historical passenger flow data for the current sim time."""
    from kafka.consumer import get_bts_flow
    flow = get_bts_flow()
    if flow is None:
        raise HTTPException(status_code=404, detail="BTS source not active or not loaded")
    return flow


@router.get("/passengers/bts/summary")
async def bts_summary():
    """Get BTS data summary statistics."""
    from kafka.consumer import get_bts_summary
    summary = get_bts_summary()
    if summary is None:
        raise HTTPException(status_code=404, detail="BTS adapter not loaded")
    return summary


@router.get("/passengers/{passenger_id}")
async def get_passenger_detail(passenger_id: str):
    pax = await get_passenger_by_id(passenger_id)
    if not pax:
        raise HTTPException(status_code=404, detail="Passenger not found")
    return pax


@router.get("/flow/summary")
async def flow_summary():
    sim_time = get_sim_time()
    security = get_security()

    by_status = await get_status_counts()

    # Compute total in airport (active statuses only)
    active = {"checked_in", "security_queue", "airside", "at_gate",
              "deplaning", "baggage_claim"}
    total = sum(v for k, v in by_status.items() if k in active)

    # Security summary with forecast
    forecast_queues = {}
    for terminal in ("A", "B", "C"):
        cp = security.get(terminal)
        forecast_queues[terminal] = cp.queue_depth  # use actual as fallback

    sec_summary_raw = security.get_summary(forecast_queues)
    sec_summary = {
        "A": {
            "queue_length": sec_summary_raw.get("terminal_a", {}).get("queue_depth", 0),
            "wait_minutes": sec_summary_raw.get("terminal_a", {}).get("wait_minutes", 0),
            "lanes_open": sec_summary_raw.get("terminal_a", {}).get("lanes_open", 0),
            "frozen": sec_summary_raw.get("terminal_a", {}).get("frozen", False),
        },
        "B": {
            "queue_length": sec_summary_raw.get("terminal_b", {}).get("queue_depth", 0),
            "wait_minutes": sec_summary_raw.get("terminal_b", {}).get("wait_minutes", 0),
            "lanes_open": sec_summary_raw.get("terminal_b", {}).get("lanes_open", 0),
            "frozen": sec_summary_raw.get("terminal_b", {}).get("frozen", False),
        },
        "C": {
            "queue_length": sec_summary_raw.get("terminal_c", {}).get("queue_depth", 0),
            "wait_minutes": sec_summary_raw.get("terminal_c", {}).get("wait_minutes", 0),
            "lanes_open": sec_summary_raw.get("terminal_c", {}).get("lanes_open", 0),
            "frozen": sec_summary_raw.get("terminal_c", {}).get("frozen", False),
        },
    }

    # Connection counts
    at_risk = get_at_risk_connections()
    conn_at_risk = sum(1 for c in at_risk if c.get("risk_level") == "at_risk")
    conn_missed = sum(1 for c in at_risk if c.get("risk_level") == "missed")

    from kafka.consumer import get_passenger_source_info
    source_info = get_passenger_source_info()

    result = {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "total_in_airport": total,
        "by_status": by_status,
        "security": sec_summary,
        "connections_at_risk": conn_at_risk,
        "connections_missed": conn_missed,
        "data_source": source_info["source"],
    }

    # Include BTS overlay data when BTS source is active
    if source_info["source"] == "bts_historical":
        from kafka.consumer import get_bts_flow
        bts = get_bts_flow()
        if bts:
            result["bts_overlay"] = bts

    return result


@router.get("/flow/heatmap")
async def flow_heatmap():
    sim_time = get_sim_time()
    zones = get_heatmap_zones()
    return {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "zones": zones,
    }


@router.get("/flow/forecast")
async def flow_forecast(
    terminal: str = Query("B", description="Terminal A, B, or C"),
    window: int = Query(90, ge=5, le=180, description="Forecast window in minutes"),
):
    terminal = terminal.upper()
    if terminal not in ("A", "B", "C"):
        raise HTTPException(status_code=400, detail="Terminal must be A, B, or C")

    sim_time = get_sim_time()
    if sim_time is None:
        raise HTTPException(status_code=503, detail="Simulation clock not available yet")
    trained = is_model_trained(terminal)

    # Build forecast points at 5-minute intervals
    forecast_points = []
    congestion_detected = False
    congestion_onset = None

    security = get_security()
    cp = security.get(terminal)

    for offset_min in range(5, window + 1, 5):
        future_time = sim_time + timedelta(minutes=offset_min)

        features = build_features(
            terminal=terminal,
            sim_time=future_time,
            weather_category="CAVOK",
            flights_next_90={"A": 0, "B": 0, "C": 0, terminal: 5},
            pax_next_90={"A": 0, "B": 0, "C": 0, terminal: 500},
            load_factor_today=0.8,
            incident_active={"A": False, "B": False, "C": False},
            adjacent_congested={"A": False, "B": False, "C": False},
        )

        pred_depth = predict(terminal, features) or 0
        # Estimate wait from predicted depth
        throughput = cp.lanes_open * 180.0
        pred_wait = (pred_depth / throughput) * 60.0 if throughput > 0 else 0

        forecast_points.append({
            "sim_time": future_time.isoformat(),
            "predicted_queue_depth": pred_depth,
            "predicted_wait_minutes": round(pred_wait, 1),
        })

        if pred_wait > 20 and not congestion_detected:
            congestion_detected = True
            congestion_onset = future_time.isoformat()

    # Congestion risk assessment
    congestion_risk = {
        "detected": congestion_detected,
        "estimated_onset_sim_time": congestion_onset,
        "confidence": 0.81 if trained and congestion_detected else 0.4 if congestion_detected else 0.0,
    }

    fi = get_feature_importance(terminal)

    return {
        "terminal": terminal,
        "sim_time": sim_time.isoformat() if sim_time else None,
        "window_minutes": window,
        "model_trained": trained,
        "forecast": forecast_points,
        "congestion_risk": congestion_risk,
        "feature_importance": fi,
    }


@router.get("/connections/at-risk")
async def connections_at_risk():
    at_risk = get_at_risk_connections()
    return {"at_risk": at_risk}


@router.get("/alerts")
async def list_alerts(
    type: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    flight_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    alerts = get_alerts_store()

    # Apply filters
    filtered = alerts
    if type:
        filtered = [a for a in filtered if a.get("type") == type]
    if urgency:
        filtered = [a for a in filtered if a.get("urgency") == urgency]
    if flight_id:
        filtered = [a for a in filtered if a.get("flight_id") == flight_id]

    return {"alerts": filtered[-limit:]}


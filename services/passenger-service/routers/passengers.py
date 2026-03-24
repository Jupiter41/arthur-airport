"""REST API router for passenger-service.

Base path: /api/v1
"""

import logging
from datetime import datetime, timedelta
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
from services.zones import get_heatmap_zones, get_density

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
    active = {"checked_in", "security_queue", "airside", "at_gate", "boarded",
              "deplaning", "baggage_claim"}
    total = sum(v for k, v in by_status.items() if k in active)

    # Security summary with forecast
    forecast_queues = {}
    for terminal in ("A", "B", "C"):
        cp = security.get(terminal)
        forecast_queues[terminal] = cp.queue_depth  # use actual as fallback

    sec_summary = security.get_summary(forecast_queues)

    # Connection counts
    at_risk = get_at_risk_connections()
    conn_at_risk = sum(1 for c in at_risk if c.get("risk_level") == "at_risk")
    conn_missed = sum(1 for c in at_risk if c.get("risk_level") == "missed")

    return {
        "sim_time": sim_time.isoformat() if sim_time else None,
        "total_in_airport": total,
        "by_status": by_status,
        "security": sec_summary,
        "connections_at_risk": conn_at_risk,
        "connections_missed": conn_missed,
    }


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
    trained = is_model_trained(terminal)

    # Build forecast points at 5-minute intervals
    forecast_points = []
    congestion_detected = False
    congestion_onset = None

    security = get_security()
    cp = security.get(terminal)

    for offset_min in range(5, window + 1, 5):
        future_time = sim_time + timedelta(minutes=offset_min) if sim_time else datetime.utcnow()

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

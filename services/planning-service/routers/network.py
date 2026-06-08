"""Network resilience & hub dependency REST API (2D — ROADMAP_USECASE.md).

Endpoints:
- GET  /api/v1/planning/network/dependency
- POST /api/v1/planning/network/disruption
- POST /api/v1/planning/network/diversify
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from engine.network import NetworkAnalyzer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/planning/network", tags=["network"])

# Lazy singleton — created on first request to avoid startup cost
_analyzer: NetworkAnalyzer | None = None


def _get_analyzer() -> NetworkAnalyzer:
    global _analyzer
    if _analyzer is None:
        try:
            _analyzer = NetworkAnalyzer()
        except (ImportError, FileNotFoundError) as e:
            raise HTTPException(
                status_code=503,
                detail=f"Network analyzer unavailable: {e}",
            )
    return _analyzer


# ── Request models ──────────────────────────────────────────


class DisruptionRequest(BaseModel):
    airline: str = Field(..., description="Airline IATA code to simulate removal of")
    reduction_pct: float = Field(
        100.0, ge=0, le=100,
        description="Percentage reduction (100 = full withdrawal)",
    )


class DiversifyRequest(BaseModel):
    target_hhi: float = Field(
        0.15, ge=0.01, le=0.90,
        description="Target Herfindahl index (lower = less concentrated)",
    )
    max_recommendations: int = Field(10, ge=1, le=50)


# ── Endpoints ───────────────────────────────────────────────


@router.get("/dependency")
async def hub_dependency():
    """Compute hub dependency scoring using Herfindahl-Hirschman Index.

    Returns airline concentration metrics, top airline shares, and
    the effective number of equal-sized airlines the current mix represents.
    """
    analyzer = _get_analyzer()
    score = analyzer.compute_dependency()
    return score.to_dict()


@router.post("/disruption")
async def simulate_disruption(body: DisruptionRequest):
    """Simulate the impact of an airline reducing or ceasing operations.

    Models the effect on daily movements, passenger throughput, gate utilisation,
    revenue, and the resulting change in hub concentration.
    """
    analyzer = _get_analyzer()
    impact = analyzer.simulate_disruption(body.airline, body.reduction_pct)

    if impact.lost_daily_departures == 0 and impact.affected_routes == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Airline '{body.airline}' not found in BTS data",
        )

    return impact.to_dict()


@router.post("/diversify")
async def recommend_diversification(body: DiversifyRequest):
    """Recommend new routes to reduce hub airline concentration.

    Uses a gravity model (demand ∝ pop_origin × pop_dest / distance²)
    to estimate potential demand for unserved destinations.
    """
    analyzer = _get_analyzer()
    recommendations = analyzer.recommend_diversification(
        target_hhi=body.target_hhi,
        max_recommendations=body.max_recommendations,
    )

    current = analyzer.compute_dependency()

    return {
        "current_hhi": round(current.herfindahl_index, 4),
        "target_hhi": body.target_hhi,
        "current_concentration": current.concentration_rating,
        "recommendations": [r.to_dict() for r in recommendations],
        "diversification_needed": bool(current.herfindahl_index > body.target_hhi),
    }

"""REST API routes for analysis-service.

Endpoints:
  GET  /api/v1/analysis/bottlenecks      → P2-1-7
  GET  /api/v1/analysis/recommendations  → P2-2-6
  POST /api/v1/analysis/what-if          → P2-3-1
  GET  /api/v1/analysis/what-if/log      → P2-3-5
  GET  /api/v1/analysis/autonomous       → P2-4-1 (get settings)
  PATCH /api/v1/analysis/autonomous      → P2-4-1 (update settings)
  GET  /api/v1/analysis/autonomous/log   → P2-4-2
"""

import logging
from typing import Any

from fastapi import APIRouter, Query

from kafka.consumer import (
    get_active_bottlenecks,
    get_active_recommendations,
    get_state,
)
from models.domain import (
    AutonomousSettings,
    BottleneckSeverity,
    BottleneckType,
    WhatIfRequest,
    WhatIfResponse,
)
from services.autonomous import get_action_log, get_settings, update_settings
from services.whatif import get_analysis_log, run_what_if

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ── P2-1-7: Bottleneck list ─────────────────────────────────


@router.get("/bottlenecks")
async def list_bottlenecks(
    severity: BottleneckSeverity | None = Query(None),
    type: BottleneckType | None = Query(None, alias="type"),
) -> dict[str, Any]:
    """Return all active bottlenecks with optional severity/type filter."""
    bottlenecks = get_active_bottlenecks()
    items = [
        bn.model_dump(mode="json")
        for bn in bottlenecks.values()
        if bn.resolved_at is None
    ]

    # Apply filters
    if severity is not None:
        items = [b for b in items if b["severity"] == severity.value]
    if type is not None:
        items = [b for b in items if b["type"] == type.value]

    return {
        "bottlenecks": items,
        "count": len(items),
        "sim_time": (
            get_state().sim_time.isoformat() if get_state().sim_time else None
        ),
    }


# ── P2-2-6: Recommendation list ─────────────────────────────


@router.get("/recommendations")
async def list_recommendations() -> dict[str, Any]:
    """Return top 3 ranked recommendations by impact/cost ratio."""
    recs = get_active_recommendations()
    return {
        "recommendations": [
            r.model_dump(mode="json") for r in recs
        ],
        "count": len(recs),
        "sim_time": (
            get_state().sim_time.isoformat() if get_state().sim_time else None
        ),
    }


# ── P2-3-1: What-if analysis ────────────────────────────────


@router.post("/what-if", response_model=WhatIfResponse)
async def what_if_analysis(request: WhatIfRequest) -> WhatIfResponse:
    """Run what-if projection for 1-3 proposed actions."""
    import time
    from metrics import whatif_queries_total, whatif_duration_seconds

    whatif_queries_total.inc()
    start = time.monotonic()

    result = run_what_if(get_state(), request)

    duration = time.monotonic() - start
    whatif_duration_seconds.observe(duration)

    return result


# ── P2-3-5: Analysis log ────────────────────────────────────


@router.get("/what-if/log")
async def what_if_log(
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return the what-if analysis log (most recent first)."""
    log = get_analysis_log()
    items = [entry.model_dump(mode="json") for entry in reversed(log)]
    return {
        "entries": items[:limit],
        "total": len(log),
    }


# ── P2-4-1: Autonomous settings ─────────────────────────────


@router.get("/autonomous")
async def get_autonomous_settings() -> dict[str, Any]:
    """Return current autonomous mode settings."""
    settings = get_settings()
    return {
        "autonomous": settings.model_dump(mode="json"),
    }


@router.patch("/autonomous")
async def update_autonomous_settings(
    body: AutonomousSettings,
) -> dict[str, Any]:
    """Update autonomous mode settings."""
    updated = update_settings(body)
    return {
        "autonomous": updated.model_dump(mode="json"),
    }


# ── P2-4-2: Autonomous action log ───────────────────────────


@router.get("/autonomous/log")
async def autonomous_action_log(
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Return the autonomous action log (most recent first)."""
    log = get_action_log()
    return {
        "actions": list(reversed(log))[:limit],
        "total": len(log),
    }

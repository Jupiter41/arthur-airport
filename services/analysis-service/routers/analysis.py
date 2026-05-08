"""REST API routes for analysis-service.

Endpoints:
  GET  /api/v1/analysis/bottlenecks      → P2-1-7
  GET  /api/v1/analysis/recommendations  → P2-2-6
  POST /api/v1/analysis/what-if          → P2-3-1
  GET  /api/v1/analysis/what-if/log      → P2-3-5
  GET  /api/v1/analysis/autonomous       → P2-4-1 (get settings)
  PATCH /api/v1/analysis/autonomous      → P2-4-1 (update settings)
  GET  /api/v1/analysis/autonomous/log   → P2-4-2
  GET  /api/v1/analysis/anomalies        → P5-3-1
  POST /api/v1/analysis/query            → P5-2-1
  POST /api/v1/analysis/nl-inject        → P5-2-2
  GET  /api/v1/analysis/narration        → P5-2-3
  PATCH /api/v1/analysis/narration       → P5-2-3 (toggle)
  POST /api/v1/analysis/report           → P5-2-4
  GET  /api/v1/analysis/llm-config       → LLM status
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
from services.anomaly import detector as anomaly_detector
from services.nlp.query import query as nl_query
from services.nlp.inject import parse_incident_command
from services.nlp.narration import narration as narration_engine
from services.nlp.report import generate_report
from services.nlp.llm import get_config as get_llm_config
from services.training_manager import manager as training_manager

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
    body: dict[str, Any],
) -> dict[str, Any]:
    """Update autonomous mode settings (partial update — only provided fields are changed)."""
    current = get_settings()
    # Merge partial body into current settings
    merged = current.model_dump(mode="json")
    merged.update({k: v for k, v in body.items() if v is not None})
    updated_model = AutonomousSettings(**merged)
    updated = update_settings(updated_model)
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


# ── P5-3-1: Anomaly detection ───────────────────────────────


@router.get("/anomalies")
async def get_anomalies() -> dict[str, Any]:
    """Return current anomaly detection status and deviations from baseline.

    P5-3-1: Isolation forest scoring with z-scores per metric.
    P5-3-3: Root cause trace for detected anomalies.
    """
    status = anomaly_detector.get_status()
    return {
        **status,
        "sim_time": (
            get_state().sim_time.isoformat() if get_state().sim_time else None
        ),
    }


# ── P5-2-1: Natural language query ──────────────────────────


@router.post("/query")
async def natural_language_query(
    body: dict[str, Any],
) -> dict[str, Any]:
    """Answer a natural language question about the current airport state.

    Body: {"question": "How many flights are delayed?"}
    """
    question = body.get("question", "")
    if not question:
        return {"error": "Missing 'question' field"}

    state = get_state()
    bottlenecks = [
        bn.model_dump(mode="json")
        for bn in get_active_bottlenecks().values()
        if bn.resolved_at is None
    ]
    recommendations = [
        r.model_dump(mode="json")
        for r in get_active_recommendations()
    ]

    return await nl_query(question, state, bottlenecks, recommendations)


# ── P5-2-2: Natural language incident injection ──────────────


@router.post("/nl-inject")
async def nl_incident_inject(
    body: dict[str, Any],
) -> dict[str, Any]:
    """Parse a natural language incident injection command.

    Body: {"command": "Inject a severe security breach in Terminal B"}
    Returns the structured incident payload ready for injection.
    """
    command = body.get("command", "")
    if not command:
        return {"error": "Missing 'command' field"}

    return await parse_incident_command(command)


# ── P5-2-3: Simulation narration ────────────────────────────


@router.get("/narration")
async def get_narration(
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Return narration settings and recent narration history."""
    return {
        "settings": narration_engine.get_settings(),
        "history": narration_engine.get_history(limit),
    }


@router.patch("/narration")
async def update_narration(
    body: dict[str, Any],
) -> dict[str, Any]:
    """Toggle narration mode on/off and update settings.

    Body: {"enabled": true, "interval_minutes": 5}
    """
    if "enabled" in body:
        narration_engine.enabled = bool(body["enabled"])
    if "interval_minutes" in body:
        narration_engine._interval = max(1, min(30, int(body["interval_minutes"])))
    return {"settings": narration_engine.get_settings()}


# ── P5-2-4: After-action report ─────────────────────────────


@router.post("/report")
async def after_action_report(
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate an after-action report for the current simulation state.

    Optional body: {"scenario_name": "Peak hour stress test"}
    """
    scenario_name = body.get("scenario_name") if body else None

    state = get_state()
    bottleneck_history = [
        bn.model_dump(mode="json")
        for bn in get_active_bottlenecks().values()
    ]
    recommendation_history = [
        r.model_dump(mode="json")
        for r in get_active_recommendations()
    ]
    autonomous_log = get_action_log()
    whatif_log = [
        entry.model_dump(mode="json")
        for entry in get_analysis_log()
    ]

    return await generate_report(
        state,
        bottleneck_history=bottleneck_history,
        recommendation_history=recommendation_history,
        autonomous_log=autonomous_log,
        whatif_log=whatif_log,
        scenario_name=scenario_name,
    )


# ── LLM configuration status ────────────────────────────────


@router.get("/llm-config")
async def llm_config() -> dict[str, Any]:
    """Return current LLM configuration and availability."""
    return get_llm_config()


# ── Training management ─────────────────────────────────────


@router.get("/training/status")
async def training_status() -> dict[str, Any]:
    """Return current training status, history, and available models."""
    return training_manager.get_status()


@router.get("/training/config")
async def training_config() -> dict[str, Any]:
    """Return training environment config, model paths, and loaded status."""
    return training_manager.get_config()


@router.post("/training/start")
async def training_start(
    model_type: str = Query(default="rl", description="Model type: rl, anomaly, forecast"),
    timesteps: int = Query(default=50000, ge=1000, le=1000000, description="Training timesteps"),
) -> dict[str, Any]:
    """Start a new training run."""
    try:
        run = await training_manager.start_training(model_type, timesteps)
        return run.to_dict()
    except ValueError as e:
        return {"error": str(e)}


@router.post("/training/stop")
async def training_stop() -> dict[str, Any]:
    """Stop the active training run."""
    stopped = await training_manager.stop_training()
    return {"stopped": stopped}

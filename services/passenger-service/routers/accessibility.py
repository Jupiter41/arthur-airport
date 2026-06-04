"""Accessibility / Special Assistance endpoints (1C — ROADMAP_USECASE.md)."""

from __future__ import annotations

from fastapi import APIRouter

from services import wheelchair

router = APIRouter(prefix="/api/v1/passengers/accessibility", tags=["accessibility"])


@router.get("/sla")
async def get_sla() -> dict:
    """Return ECAC Doc 30 SLA compliance for special-assistance passengers.

    Reports the rolling 24-hour window: % of SA pax reaching the gate before
    the boarding cutoff (T-15 by default), per-terminal breakdown, and the
    mean dispatch wait time. ``compliant`` is true when ``actual_pct`` ≥ target.
    """
    return wheelchair.sla_summary()


@router.get("/staffing")
async def get_staffing() -> dict:
    """Recommend wheelchair agents per terminal based on recent demand."""
    return wheelchair.staffing_recommendation()


@router.get("/resources")
async def get_resources() -> dict:
    """Snapshot of pool sizes, in-use chairs, and queue depth per terminal."""
    return wheelchair.resources_snapshot()

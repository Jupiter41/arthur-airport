"""Read-only durable decision timeline endpoints."""
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from models.decisions import DecisionList, DecisionTimeline

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("", response_model=DecisionList)
async def decision_timelines(
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    bottleneck_id: str | None = None, incident_id: str | None = None, status: str | None = None,
) -> dict[str, Any]:
    from services.decision_history import list_timelines
    items = await list_timelines()
    if bottleneck_id:
        items = [item for item in items if item["bottleneck_id"] == bottleneck_id]
    if incident_id:
        items = [item for item in items if item["parameters"].get("incident_id") == incident_id
                 or ((item.get("bottleneck") or {}).get("metrics") or {}).get("incident_id") == incident_id]
    if status:
        items = [item for item in items if item["status"] == status]
    return {"decisions": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


@router.get("/{decision_id}", response_model=DecisionTimeline)
async def decision_timeline(decision_id: str) -> dict[str, Any]:
    from services.decision_history import list_timelines
    item = next((item for item in await list_timelines() if item["id"] == decision_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return item



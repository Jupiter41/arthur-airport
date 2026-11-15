"""Read-only durable decision timeline endpoints."""
import re
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from models.decisions import DecisionList, DecisionTimeline

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("", response_model=DecisionList)
async def decision_timelines(
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    bottleneck_id: str | None = None, incident_id: str | None = None, status: str | None = None,
    q: str | None = Query(None, max_length=200),
    terminal: str | None = Query(None, pattern="^[ABC]$"),
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
    if q and q.strip():
        needle = q.strip().casefold()
        items = [item for item in items if needle in " ".join(str(value or "") for value in (
            item.get("description"), item.get("id"), item.get("bottleneck_id"),
            item.get("action_type"), (item.get("bottleneck") or {}).get("zone"),
        )).casefold()]
    if terminal:
        def matches(item: dict[str, Any]) -> bool:
            parameters = item.get("parameters") or {}
            zone = str((item.get("bottleneck") or {}).get("zone") or "")
            explicit = str(parameters.get("terminal") or parameters.get("terminal_id") or "")
            normalized = re.sub(r"^(?:terminal[-_ ]?|T-)", "", explicit, flags=re.I).upper()
            return normalized == terminal or bool(re.search(
                rf"(?:^|[-_ ]){terminal}(?:$|[-_ ])", zone, flags=re.I,
            ))
        items = [item for item in items if matches(item)]
    return {"decisions": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


@router.get("/{decision_id}", response_model=DecisionTimeline)
async def decision_timeline(decision_id: str) -> dict[str, Any]:
    from services.decision_history import list_timelines
    item = next((item for item in await list_timelines() if item["id"] == decision_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return item



"""REST API routers for incident-service."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from db.neo4j import (
    get_affected_flights,
    get_cascade_tree,
    get_incident_by_id,
    get_incidents,
    count_incidents,
)
from kafka.consumer import get_active_alerts, get_sim_time
from models.domain import (
    AlertsResponse,
    AlertItem,
    CascadeTreeNode,
    ContainRequest,
    IncidentDetail,
    IncidentListResponse,
    IncidentSummary,
    InjectRequest,
    ProtocolStatusResponse,
    ResolveRequest,
    TimelineEntry,
)
from services.lifecycle import contain_incident, create_incident, resolve_incident
from services.protocols import get_protocol_manager, PROTOCOL_ACTIONS
from services.reports import build_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["incidents"])


# ── List incidents ────────────────────────────────────────────


@router.get("/incidents")
async def list_incidents(
    status: str | None = None,
    type: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> IncidentListResponse:
    limit = min(limit, 100)
    incidents = await get_incidents(
        status=status, type_filter=type, severity=severity, limit=limit
    )
    total = await count_incidents(status=status)

    summaries = []
    for inc in incidents:
        summaries.append(IncidentSummary(
            id=inc["id"],
            type=inc.get("type", ""),
            severity=inc.get("severity", ""),
            status=inc.get("status", ""),
            trigger=inc.get("trigger", ""),
            title=inc.get("title", ""),
            location=inc.get("location", ""),
            started_at=inc.get("started_at", ""),
            resolved_at=inc.get("resolved_at"),
            protocol=inc.get("protocol", ""),
            cascade_depth=inc.get("cascade_depth", 0),
        ))

    return IncidentListResponse(total=total, incidents=summaries)


# ── Get incident detail ──────────────────────────────────────


@router.get("/incidents/{incident_id}")
async def get_incident_detail(incident_id: str) -> IncidentDetail:
    incident = await get_incident_by_id(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Build cascade tree
    cascade_nodes = await get_cascade_tree(incident_id)
    cascade_tree = _build_cascade_tree(cascade_nodes, incident)

    # Get affected flights
    affected = await get_affected_flights(incident_id)

    # Build timeline
    timeline = _build_timeline(incident)

    # Estimated resolution
    estimated_resolution = None
    if incident.get("ttr_remaining") is not None and incident.get("status") == "active":
        sim_time = get_sim_time()
        if sim_time:
            from datetime import timedelta
            est = sim_time + timedelta(minutes=incident["ttr_remaining"])
            estimated_resolution = est.isoformat()

    return IncidentDetail(
        id=incident["id"],
        type=incident.get("type", ""),
        severity=incident.get("severity", ""),
        status=incident.get("status", ""),
        trigger=incident.get("trigger", ""),
        title=incident.get("title", ""),
        description=incident.get("description", ""),
        location=incident.get("location", ""),
        protocol=incident.get("protocol", ""),
        started_at=incident.get("started_at", ""),
        resolved_at=incident.get("resolved_at"),
        contained_at=incident.get("contained_at"),
        estimated_resolution_at=estimated_resolution,
        ttr_remaining=incident.get("ttr_remaining"),
        cascade_tree=cascade_tree,
        affected_flights=affected or [],
        timeline=timeline or [],
    )


# ── Inject incident ──────────────────────────────────────────


@router.post("/incidents/inject", status_code=201)
async def inject_incident(req: InjectRequest) -> dict:
    sim_time = get_sim_time()
    if sim_time is None:
        raise HTTPException(status_code=503, detail="Simulation clock not available yet")

    incident = await create_incident(
        type=req.type,
        severity=req.severity,
        location=req.location,
        trigger="manual",
        sim_time=sim_time,
        description=req.description,
        subtype=req.subtype,
    )
    return incident


# ── Contain incident ──────────────────────────────────────────


@router.post("/incidents/{incident_id}/contain")
async def contain_incident_endpoint(incident_id: str, req: ContainRequest) -> dict:
    sim_time = get_sim_time()
    if sim_time is None:
        raise HTTPException(status_code=503, detail="Simulation clock not available yet")

    result = await contain_incident(incident_id, sim_time, req.note)
    if not result:
        raise HTTPException(status_code=404, detail="Incident not found or cannot be contained")
    return result


# ── Resolve incident ──────────────────────────────────────────


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident_endpoint(incident_id: str, req: ResolveRequest) -> dict:
    sim_time = get_sim_time()
    if sim_time is None:
        raise HTTPException(status_code=503, detail="Simulation clock not available yet")

    result = await resolve_incident(incident_id, sim_time, req.note)
    if not result:
        raise HTTPException(status_code=404, detail="Incident not found or cannot be resolved")
    return result


# ── Incident report ──────────────────────────────────────────


@router.get("/incidents/{incident_id}/report")
async def get_incident_report(incident_id: str) -> dict:
    sim_time = get_sim_time()
    if sim_time is None:
        raise HTTPException(status_code=503, detail="Simulation clock not available yet")

    report = await build_report(incident_id, sim_time)
    if not report:
        raise HTTPException(status_code=404, detail="Incident not found")
    return report


# ── Alerts ────────────────────────────────────────────────────


@router.get("/alerts")
async def list_alerts() -> AlertsResponse:
    alerts = get_active_alerts()

    # Update ages based on current sim_time
    sim_time = get_sim_time()
    items = []
    for a in alerts:
        age = 0
        if sim_time and a.get("at"):
            try:
                delta = sim_time - datetime.fromisoformat(a["at"])
                age = max(0, int(delta.total_seconds() / 60))
            except (ValueError, TypeError):
                pass

        items.append(AlertItem(
            incident_id=a.get("incident_id", ""),
            severity=a.get("severity", "medium"),
            title=a.get("title", ""),
            short_message=a.get("short_message", ""),
            affected_zones=a.get("affected_zones", []),
            dashboard_color=a.get("dashboard_color", "yellow"),
            sound_alert=a.get("sound_alert", False),
            age_minutes=age,
            at=a.get("at", ""),
        ))

    return AlertsResponse(alerts=items)


# ── Protocols ─────────────────────────────────────────────────


@router.get("/protocols")
async def protocol_status() -> ProtocolStatusResponse:
    pm = get_protocol_manager()
    effective = pm.effective_protocol()
    return ProtocolStatusResponse(
        effective_protocol=effective,
        effective_description=PROTOCOL_ACTIONS.get(effective, "") if effective else "",
        active_protocols=pm.get_active_protocols(),
        evacuation_active=pm.is_evacuation_active(),
    )


# ── Helper functions ─────────────────────────────────────────


def _build_cascade_tree(nodes: list[dict], incident: dict) -> CascadeTreeNode:
    """Build a nested cascade tree from flat list of nodes with depth."""
    if not nodes:
        return CascadeTreeNode(
            id=incident.get("id", ""),
            type=incident.get("type", ""),
            severity=incident.get("severity", ""),
            status=incident.get("status", ""),
            description=incident.get("description", ""),
            children=[],
        )

    # Build lookup by id
    node_map: dict[str, CascadeTreeNode] = {}
    for n in nodes:
        node_map[n["id"]] = CascadeTreeNode(
            id=n["id"],
            type=n.get("type", ""),
            severity=n.get("severity", ""),
            status=n.get("status", ""),
            description=n.get("description", ""),
            children=[],
        )

    # The root is depth 0 (first node)
    root_id = nodes[0]["id"]

    # For each node at depth > 0, find its parent via Neo4j SPAWNED traversal
    # Since cascade_tree returns depth-ordered, we need to build parent-child
    # We'll use a simpler approach: group by depth and link via shared prefix
    # Actually, we already have the tree structure from SPAWNED relationships
    # The nodes list is ordered by depth — we need to rebuild the tree
    # Use a BFS-like approach: for each node, look up children from the DB
    # But that's async — let's build from the flat list instead
    
    # Since the tree is returned from Neo4j with the path, and each child
    # at depth N is reached via parent at depth N-1, we have a natural order.
    # Build parent tracking using the database
    # For simplicity in the sync context, build a tree from depth levels
    
    depth_groups: dict[int, list[dict]] = {}
    for n in nodes:
        d = n.get("depth", 0)
        depth_groups.setdefault(d, []).append(n)

    # Root node
    root_node = node_map.get(root_id)
    if not root_node:
        return CascadeTreeNode(
            id=incident.get("id", ""),
            type=incident.get("type", ""),
            severity=incident.get("severity", ""),
            status=incident.get("status", ""),
            description=incident.get("description", ""),
            children=[],
        )

    # For depth > 0, attach to all parents at depth - 1
    # This is approximate but works for linear cascade chains
    max_depth = max(depth_groups.keys()) if depth_groups else 0
    for d in range(1, max_depth + 1):
        children_at_d = depth_groups.get(d, [])
        parents_at_prev = depth_groups.get(d - 1, [])
        for child in children_at_d:
            child_node = node_map.get(child["id"])
            if not child_node:
                continue
            # Attach to the parent that shares the same location (best heuristic)
            attached = False
            for parent in parents_at_prev:
                parent_node = node_map.get(parent["id"])
                if parent_node and parent.get("location") == child.get("location"):
                    parent_node.children.append(child_node)
                    attached = True
                    break
            if not attached and parents_at_prev:
                # Fallback: attach to first parent at previous depth
                parent_node = node_map.get(parents_at_prev[0]["id"])
                if parent_node:
                    parent_node.children.append(child_node)

    return root_node


def _build_timeline(incident: dict) -> list[TimelineEntry]:
    """Build timeline entries for an incident."""
    entries = []

    if incident.get("started_at"):
        entries.append(TimelineEntry(
            status="active",
            note="Incident created",
            at=incident["started_at"],
        ))

    protocol = incident.get("protocol", "")
    if protocol and incident.get("started_at"):
        entries.append(TimelineEntry(
            status="active",
            note=f"{protocol} protocol activated",
            at=incident["started_at"],
        ))

    if incident.get("contained_at"):
        entries.append(TimelineEntry(
            status="contained",
            note=incident.get("resolution_note", "Incident contained"),
            at=incident["contained_at"],
        ))

    if incident.get("resolved_at"):
        entries.append(TimelineEntry(
            status="resolved",
            note=incident.get("resolution_note", "Incident resolved"),
            at=incident["resolved_at"],
        ))

    return entries

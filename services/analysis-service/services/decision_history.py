"""Durable decision evidence and read-only timeline projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from db.neo4j import get_driver


def _time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def record_stage(document: dict, stage: str, clock: datetime, **details: object) -> None:
    document.setdefault("history", []).append({"stage": stage, "at": clock.isoformat(), "details": details})


async def save_discovery(tx, bottlenecks: list[dict], recommendations: list[dict], at: str) -> None:
    """Keep detected/resolved evidence after it leaves the hot discovery snapshot."""
    for bn in bottlenecks:
        await (await tx.run(
            "MERGE (d:DecisionRecord {id: $id}) "
            "ON CREATE SET d.detected_at = $at, d.bottleneck = $bottleneck "
            "SET d.ranked_at = CASE WHEN d.recommendations IS NULL OR d.recommendations = '[]' THEN $ranked_at ELSE d.ranked_at END, "
            "d.recommendations = CASE WHEN d.recommendations IS NULL OR d.recommendations = '[]' THEN $recommendations ELSE d.recommendations END, "
            "d.resolved_at = $resolved",
            id=bn["id"], at=bn["detected_at"], bottleneck=json.dumps(bn, allow_nan=False),
            recommendations=json.dumps([r for r in recommendations if r["bottleneck_id"] == bn["id"]], allow_nan=False),
            resolved=bn.get("resolved_at"),
            ranked_at=at,
        )).consume()


def context_from_discovery(discovery: dict | None, document: dict) -> dict | None:
    if not discovery:
        return None
    bn = next((b for b in discovery.get("bottlenecks", []) if b["id"] == document.get("bottleneck_id")), None)
    recs = discovery.get("recommendations", [])
    selected = next((r for r in recs if r["id"] == document.get("recommendation_id")), None)
    if bn is None or selected is None:
        return None
    signals = {}
    for row in discovery.get("graph", {}).get("cost", []):
        runtime = json.loads(row["document"])
        totals = runtime.get("days", {}).get(str(runtime.get("sim_day", 1)), {}).get("cost", {})
        signals = {key: totals.get(key) for key in ("total_cost_eur", "total_revenue_eur", "eu261_exposure", "last_updated")}
    return deepcopy({"bottleneck": bn, "recommendation": selected, "alternatives": recs,
                     "captured_at": discovery["clock"]["sim_time"],
                     "financial_signals": signals})


def timeline(record: dict | None, proposal: dict | None) -> dict:
    context = (proposal or {}).get("decision_context") or {}
    bn = context.get("bottleneck") or (record or {}).get("bottleneck")
    recs = context.get("alternatives") or (record or {}).get("recommendations", [])
    selected = context.get("recommendation") or next((r for r in recs if r.get("bottleneck_id") == (bn or {}).get("id")), None)
    stages = []
    ranked_at = context.get("captured_at") or (record or {}).get("ranked_at")
    if bn:
        stages.append({"stage": "detected", "at": bn["detected_at"], "details": {"root_cause": bn["root_cause"]}})
    if selected or recs:
        initial_prediction = (selected or next(iter(recs), {})).get("projection")
        if initial_prediction:
            stages.append({"stage": "predicted", "at": ranked_at,
                           "details": initial_prediction})
        stages.append({"stage": "ranked", "at": ranked_at,
                       "details": {"evidence": "proposal_snapshot" if context else "discovery_snapshot"}})
    history = deepcopy((proposal or {}).get("history") or [])
    stages.extend(history)
    if (record or {}).get("resolved_at"):
        stages.append({"stage": "resolved", "at": record["resolved_at"], "details": {"condition": "bottleneck_resolved"}})
    p = proposal or {}
    # Legacy timestamps are useful evidence, but missing receipts are not invented.
    if proposal and not history:
        stages.append({"stage": "proposed", "at": p["proposed_at"], "details": {"legacy": True}})
        for key, stage in (("decided_at", "rejected" if p.get("status") == "rejected" else "approved"),
                           ("dispatched_at", "dispatched"), ("executed_at", "executed"),
                           ("outcome_measured_at", "measured")):
            if p.get(key):
                stages.append({"stage": stage, "at": p[key], "details": {"legacy": True}})
    baseline = p.get("baseline") or {}
    prediction = baseline.get("predicted")
    if prediction:
        stages.append({"stage": "dispatch_prediction", "at": baseline.get("observed_at"), "details": prediction})
    # Stable sort preserves approval-before-dispatch and receipt-before-measurement ties.
    order = {name: i for i, name in enumerate(("detected", "predicted", "ranked", "proposed", "approved", "dispatch_prediction", "dispatched", "executed", "rejected", "failed", "measured"))}
    stages.sort(key=lambda s: (_time(s.get("at")), order.get(s["stage"], 99)))
    outcome = p.get("actual_outcome")
    status = p.get("status") or ("resolved" if (record or {}).get("resolved_at") else "detected")
    if status == "executed":
        status = "measured" if outcome is not None else "awaiting_measurement"
    return {"id": p.get("id") or (record or {})["id"], "bottleneck_id": p.get("bottleneck_id") or (bn or {}).get("id"),
            "bottleneck": bn, "recommendation": selected, "alternatives": recs,
            "description": p.get("description") or (bn or {}).get("root_cause", "Historical decision"),
            "status": status, "proposal_status": p.get("status"), "proposal_id": p.get("id"),
            "action_type": p.get("action_type"), "parameters": p.get("parameters", {}),
            "stages": stages, "predicted": prediction, "outcome": outcome,
            "receipt": p.get("owner_receipt"), "dispatch_attempts": p.get("dispatch_attempts", 0),
            "failure_reason": p.get("failure_reason") or p.get("reject_reason"),
            "effect_model_version": p.get("effect_model_version") or (selected or {}).get("effect_model_version", "legacy"),
            "context_available": bool(context), "financial_signals": context.get("financial_signals", {}),
            "action_available": bool(not proposal and (record or {}).get("action_available") and selected and selected.get("executable")),
            "updated_at": next((s["at"] for s in reversed(stages) if s.get("at")), None)}


async def list_timelines() -> list[dict]:
    """Read records and proposals in one Neo4j read transaction, across restarts."""
    async def read(tx):
        rows = await (await tx.run(
            "MATCH (d:DecisionRecord) RETURN d.id AS id, d.bottleneck AS bottleneck, "
            "d.recommendations AS recommendations, d.resolved_at AS resolved_at, d.ranked_at AS ranked_at",
        )).data()
        records = {r["id"]: {**r, "bottleneck": json.loads(r["bottleneck"]),
                                 "recommendations": json.loads(r["recommendations"] or "[]")} for r in rows}
        result = await tx.run("MATCH (p:ActionProposal) RETURN p.document AS document")
        proposals = [json.loads(r["document"]) for r in await result.data()]
        row = await (await tx.run("MATCH (s:AnalysisRuntime {id: 'discovery'}) RETURN s.document AS document")).single()
        current = json.loads(row["document"]) if row and row.get("document") else {}
        active_ids = {b["id"] for b in current.get("bottlenecks", [])}
        for record in records.values():
            if record["id"] in active_ids:
                record.update(recommendations=[r for r in current.get("recommendations", [])
                                               if r["bottleneck_id"] == record["id"]],
                              ranked_at=current["clock"]["sim_time"], action_available=True)
        covered = {p.get("bottleneck_id") for p in proposals}
        items = [timeline(records.get(p.get("bottleneck_id")), p) for p in proposals]
        items.extend(timeline(r, None) for key, r in records.items() if key not in covered)
        return sorted(items, key=lambda item: (_time(item["updated_at"]), item["id"]), reverse=True)
    async with get_driver().session() as session:
        return await session.execute_read(read)

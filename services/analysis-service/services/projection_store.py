"""Graph-derived discovery with serialized ownership and atomic fact publication."""
from __future__ import annotations

from hashlib import sha256
import json

from pydantic import TypeAdapter

from db.neo4j import get_driver, load_operational_projection, query_connection_clusters
from models.domain import Bottleneck, Recommendation
from services import proposal_store
from services.approval_queue import Proposal
from services.detectors import check_resolved, detect_all
from services.recommender import generate_recommendations
from services.state import OperationalState, _parse_dt, _utc

VERSION = 1


def _json(value: object) -> str:
    def encode(item: object) -> str:
        if hasattr(item, "isoformat"):
            return item.isoformat()
        raise TypeError(f"Unsupported projection value: {type(item).__name__}")
    return json.dumps(value, default=encode, sort_keys=True, allow_nan=False)


def restore(document: dict) -> tuple[OperationalState, dict[str, Bottleneck], list[Recommendation]]:
    if document["version"] != VERSION:
        raise ValueError("Unsupported analysis discovery version")
    state = OperationalState()
    state.on_clock_tick(document["clock"])
    state.restore_graph(document["graph"])
    state.makeup_over_threshold_since.update({
        key: _parse_dt(value) for key, value in document.get("threshold_timers", {}).items()
    })
    bottlenecks = {row["id"]: Bottleneck.model_validate(row) for row in document["bottlenecks"]}
    return state, bottlenecks, [Recommendation.model_validate(row) for row in document["recommendations"]]


async def load() -> dict | None:
    async with get_driver().session() as session:
        row = await (await session.run(
            "MATCH (s:AnalysisRuntime {id: 'discovery'}) RETURN s.document AS document",
        )).single()
    return json.loads(row["document"]) if row and row["document"] else None


def _rec_key(rec: Recommendation) -> str:
    return _json([rec.bottleneck_id, rec.action_type.value, rec.parameters])


async def evaluate() -> tuple[dict | None, list[Bottleneck], list[Bottleneck]]:
    """Commit one discovery per clock offset + graph input identity.

    Reconciliation can run after late owner facts at the same clock. Replays of
    identical committed inputs restore the result, including its entity IDs.
    """
    async def apply(tx, revision):
        clock_row = await (await tx.run(
            "MATCH (s:AnalysisRuntime {id: 'actions'}) RETURN s.clock AS clock, s.clock_offset AS offset",
        )).single()
        if not clock_row or not clock_row["clock"]:
            return None, [], []
        clock = json.loads(clock_row["clock"])
        row = await (await tx.run(
            "MATCH (s:AnalysisRuntime {id: 'discovery'}) RETURN s.document AS document",
        )).single()
        previous = json.loads(row["document"]) if row and row["document"] else None
        graph = await load_operational_projection(tx=tx)
        graph["connections"] = await query_connection_clusters(tx=tx)
        proposals_result = await tx.run("MATCH (p:ActionProposal) RETURN p.document AS document")
        graph["proposals"] = [json.loads(item["document"]) for item in await proposals_result.data()]
        # Canonicalize Neo4j temporal values and unordered database row sets.
        graph = json.loads(_json(graph))
        graph = {key: sorted(rows, key=_json) for key, rows in graph.items()}
        digest = sha256(_json(graph).encode()).hexdigest()
        if (previous and previous["clock_offset"] == clock_row["offset"]
                and previous["input_digest"] == digest):
            return previous, [], []
        if previous:
            state, active, old_recs = restore(previous)
        else:
            state, active, old_recs = OperationalState(), {}, []
        old_clock = state.sim_time
        state.on_clock_tick(clock)
        state.restore_graph(graph)
        now = state.sim_time
        assert now is not None
        rewind = old_clock is not None and _utc(now) < _utc(old_clock)
        resolved = []
        for bn in list(active.values()):
            if rewind or check_resolved(state, bn):
                bn.resolved_at = now
                resolved.append(bn)
                del active[bn.id]
        new = detect_all(state, active)
        active.update({bn.id: bn for bn in new})
        proposals = [TypeAdapter(Proposal).validate_python(item) for item in graph["proposals"]]
        recs = generate_recommendations(state, list(active.values()), proposals=proposals)
        # Preserve recommendation identities through refresh/restart/replicas.
        reusable = {_rec_key(rec): rec for rec in old_recs if _utc(rec.expiry_sim_time) > _utc(now)}
        for rec in recs:
            prior = reusable.get(_rec_key(rec))
            if prior:
                rec.id, rec.expiry_sim_time = prior.id, prior.expiry_sim_time
        document = {
            "version": VERSION, "revision": revision, "clock": clock,
            "clock_offset": clock_row["offset"], "input_digest": digest, "graph": graph,
            "bottlenecks": [bn.model_dump(mode="json") for bn in active.values()],
            "recommendations": [rec.model_dump(mode="json") for rec in recs],
            "threshold_timers": {key: value.isoformat() if value else None
                                 for key, value in state.makeup_over_threshold_since.items()},
        }
        await (await tx.run(
            "MERGE (s:AnalysisRuntime {id: 'discovery'}) SET s.document = $document",
            document=_json(document),
        )).consume()
        messages = [proposal_store._fact("BottleneckDetected", bn.model_dump(mode="json"), now) for bn in new]
        for bn in resolved:
            fact = proposal_store._fact("BottleneckResolved", {"id": bn.id, "bottleneck_id": bn.id}, now)
            messages.append(fact)
        messages.extend(proposal_store._fact("RecommendationGenerated", rec.model_dump(mode="json"), now)
                        for rec in recs)
        # Also expose empty replacements and timer-only updates as durable facts.
        messages.append(proposal_store._fact("AnalysisProjectionUpdated", {
            "id": "discovery", "revision": revision, "clock_offset": clock_row["offset"],
            "bottleneck_ids": list(active), "recommendation_ids": [rec.id for rec in recs],
        }, now))
        await proposal_store._outbox(tx, revision, messages)
        return document, new, resolved

    return await proposal_store._transaction(apply)

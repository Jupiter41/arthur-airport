"""Persisted evidence survives refresh, retries and rejected/failed actions."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import importlib
import json

import pytest

from tests.conftest import import_service_module
from tests.unit.test_proposal_store import context as proposal_context, create, document, NOW


context = proposal_context


def test_human_approval_captures_the_dispatch_baseline_and_retains_it_on_retry(context, monkeypatch):
    _, execution, _, driver = context
    proposal = asyncio.run(create(context))
    captured = {"observed_at": NOW.isoformat(), "predicted": {"metric": "security_wait_minutes", "delta": -6},
                "controls": {"Terminal B": {"wait": 20}, "Terminal C": {"wait": 20}}}
    monkeypatch.setattr(execution, "_baseline", lambda proposal, clock: deepcopy(captured))
    first = asyncio.run(execution.approve(proposal.id, NOW, decided_by="teacher"))
    assert first["status"] == "dispatched" and first["applied"] is False
    assert document(driver, proposal.id)["baseline"] == captured
    captured["predicted"]["delta"] = -100
    asyncio.run(execution.approve(proposal.id, NOW + timedelta(minutes=6), decided_by="teacher"))
    assert document(driver, proposal.id)["baseline"]["predicted"]["delta"] == -6


def discovery():
    return {"clock": {"sim_time": NOW.isoformat()}, "bottlenecks": [{
        "id": "synthetic-bottleneck", "type": "security_queue", "severity": "critical", "zone": "Terminal B",
        "root_cause": "Synthetic queue exceeds capacity", "estimated_duration_minutes": 30,
        "affected_entity_count": 300, "detected_at": NOW.isoformat(), "metrics": {"queue_depth": 300},
    }], "recommendations": [{"id": "synthetic-rec", "bottleneck_id": "synthetic-bottleneck",
        "action_type": "open_security_lane", "description": "Open one lane", "expected_impact": "Wait reduction",
        "cost": "One staff member", "confidence_score": 0.85, "priority_rank": 1,
        "expiry_sim_time": (NOW + timedelta(minutes=30)).isoformat(), "parameters": {"terminal": "B", "new_lane_count": 5},
        "impact_value": 1800, "cost_value": 25, "priority_score": 61.2,
        "projection": {"metric": "security_wait_minutes", "delta": -6}, "executable": True}], "graph": {}}


def test_immutable_ranking_context_and_atomic_lifecycle_receipt(context):
    store, execution, _, driver = context
    driver.db["discovery"] = json.dumps(discovery())
    proposal = asyncio.run(create(context))
    original = document(driver, proposal.id)["decision_context"]
    changed = discovery()
    changed["recommendations"][0]["priority_score"] = 999
    driver.db["discovery"] = json.dumps(changed)
    baseline = {"observed_at": NOW.isoformat(), "predicted": {"metric": "security_wait_minutes", "delta": -6}}
    asyncio.run(store.dispatch(proposal.id, NOW, approve_by="teacher", baseline=baseline))
    asyncio.run(store.dispatch(proposal.id, NOW + timedelta(minutes=6)))
    payload = {"command_id": proposal.id, "command_type": "OpenSecurityLane"}
    assert not asyncio.run(store.receipt("CommandExecuted", payload, NOW, "flights.events"))
    assert asyncio.run(store.receipt("CommandExecuted", payload, NOW + timedelta(minutes=7), "passengers.events"))
    outcome = {"measurable": True, "attribution": {"method": "pre_post", "calibration_eligible": False}}
    asyncio.run(store.record_outcome(proposal.id, outcome, NOW + timedelta(minutes=38)))
    assert asyncio.run(store.record_outcome(proposal.id, outcome, NOW + timedelta(minutes=39))) is None
    saved = document(driver, proposal.id)
    assert saved["decision_context"] == original
    assert [s["stage"] for s in saved["history"]] == ["proposed", "approved", "dispatched", "dispatched", "executed", "measured"]
    assert saved["owner_receipt"]["payload"] == payload
    assert saved["owner_receipt"]["topic"] == "passengers.events"
    history = importlib.import_module("services.decision_history")
    view = history.timeline(None, saved)
    assert view["status"] == "measured" and view["recommendation"]["priority_score"] == 61.2
    assert "effect_replay" not in json.dumps(view)
    # A different process needs only the committed document, not approval cache.
    execution.approval_queue.clear()
    assert history.timeline(None, deepcopy(saved)) == view


def test_rejected_and_failed_are_distinct_with_original_receipts(context):
    store, _, _, driver = context
    proposal = asyncio.run(create(context))
    asyncio.run(store.reject(proposal.id, NOW, "teacher", "Do not intervene"))
    history = importlib.import_module("services.decision_history")
    rejected = history.timeline(None, document(driver, proposal.id))
    assert rejected["status"] == "rejected" and rejected["receipt"] is None
    next_proposal = asyncio.run(create(context, recommendation_id="second-rec"))
    asyncio.run(store.dispatch(next_proposal.id, NOW, approve_by="teacher"))
    asyncio.run(store.receipt("CommandRejected", {"command_id": next_proposal.id,
        "command_type": "OpenSecurityLane", "reason": "Checkpoint unavailable"}, NOW, "passengers.events"))
    failed = history.timeline(None, document(driver, next_proposal.id))
    assert failed["status"] == "failed" and failed["receipt"]["event_type"] == "CommandRejected"
    assert failed["failure_reason"] == "Checkpoint unavailable"


def test_legacy_evidence_is_labelled_and_never_fabricates_receipts(context):
    history = importlib.import_module("services.decision_history")
    _, _, _, driver = context
    proposal = asyncio.run(create(context, human=False))
    saved = document(driver, proposal.id)
    saved.update(status="executed", executed_at=NOW.isoformat(), history=[], decision_context=None, baseline=None)
    view = history.timeline(None, saved)
    assert view["status"] == "awaiting_measurement"
    assert view["context_available"] is False and view["receipt"] is None and view["predicted"] is None
    assert all(stage["details"]["legacy"] for stage in view["stages"])


def test_failed_transaction_cannot_publish_a_partial_timeline(context):
    store, _, _, driver = context
    proposal = asyncio.run(create(context))
    before = document(driver, proposal.id)
    driver.fail_after_outbox = True
    with pytest.raises(RuntimeError):
        asyncio.run(store.dispatch(proposal.id, NOW, approve_by="teacher"))
    assert document(driver, proposal.id) == before


def test_timeline_filtering_pagination_and_detail(monkeypatch):
    routes = import_service_module("analysis", "routers.decisions")
    history = importlib.import_module("services.decision_history")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    rows = [history.timeline({"id": "bn-1", "bottleneck": discovery()["bottlenecks"][0], "recommendations": [], "resolved_at": None}, None)]
    async def read():
        return deepcopy(rows)
    monkeypatch.setattr(history, "list_timelines", read)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/analysis")
    with TestClient(app) as client:
        assert client.get("/api/v1/analysis/decisions?limit=0").status_code == 422
        response = client.get("/api/v1/analysis/decisions?limit=1").json()
        assert response["total"] == 1 and response["decisions"][0]["id"] == "bn-1"
        assert client.get("/api/v1/analysis/decisions?status=failed").json()["total"] == 0
        assert client.get("/api/v1/analysis/decisions?offset=1").json()["decisions"] == []
        assert client.get("/api/v1/analysis/decisions/bn-1").status_code == 200
        assert client.get("/api/v1/analysis/decisions/missing").status_code == 404

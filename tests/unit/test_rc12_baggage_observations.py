"""Durable arrival observations and mode-independent collection facts."""
import asyncio
import importlib
import json
from copy import deepcopy
from datetime import datetime

import pytest

from tests.conftest import import_service_module
from tests.unit.test_passenger_g1_closeout import Driver

NOW = datetime(2024, 6, 15, 12)


def context(monkeypatch):
    db = import_service_module("passenger", "db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    return importlib.import_module("services.baggage_observations"), driver


def payload(status="collected"):
    return {"baggage_id": "b1", "passenger_id": "p1", "flight_id": "f1",
            "new_status": status, "scan_zone": "arrival-belt-3"}


def test_collection_is_durable_before_passenger_exists_and_duplicate_is_inert(monkeypatch):
    obs, driver = context(monkeypatch)
    asyncio.run(obs.observe(payload(), NOW, "input"))
    assert driver.db["observations"]["p1"]["collected_at"] == NOW.isoformat()
    assert "p1" not in driver.db["pax"]
    before = deepcopy(driver.db)
    asyncio.run(obs.observe(payload(), NOW, "same-transition-other-envelope"))
    assert driver.db == before
    [fact] = [json.loads(row["document"]) for row in driver.db["outbox"].values()]
    assert fact["event_type"] == "PassengerBaggageObserved"


@pytest.mark.parametrize("failure", ["MERGE (o:PassengerBaggageObservation", "CREATE (e:PassengerOutbox"])
def test_failed_observation_rolls_back_inbox_observation_and_fact(monkeypatch, failure):
    obs, driver = context(monkeypatch)
    before = deepcopy(driver.db)
    driver.fail_once = failure
    with pytest.raises(RuntimeError):
        asyncio.run(obs.observe(payload(), NOW, "input"))
    assert driver.db == before
    asyncio.run(obs.observe(payload(), NOW, "input"))
    assert driver.db["observations"]["p1"]["collected_at"] == NOW.isoformat()


@pytest.mark.parametrize("status", ["deplaning", "customs", "boarded", "departed_airport", "baggage_claim"])
def test_carousel_requires_actual_claim_lifecycle(monkeypatch, status):
    obs, driver = context(monkeypatch)
    driver.db["pax"]["p1"] = {"status": status, "zone": "original"}
    moved = asyncio.run(obs.observe(payload("on_carousel"), NOW, "input"))
    assert bool(moved) == (status == "baggage_claim")
    assert driver.db["pax"]["p1"]["zone"] == ("carousel-3" if moved else "original")
    assert driver.db["observations"]["p1"]["carousel_zone"] == "carousel-3"


def test_bootstrap_observation_cannot_move_an_ahead_of_checkpoint_claimant(monkeypatch):
    obs, driver = context(monkeypatch)
    driver.db["pax"]["p1"] = {"status": "baggage_claim", "zone": "original"}
    assert not asyncio.run(obs.observe(payload("on_carousel"), NOW, "bootstrap", allow_move=False))
    assert driver.db["pax"]["p1"]["zone"] == "original"


def test_bulk_planner_keeps_named_collection_and_carousel_facts(monkeypatch):
    from tests.unit.test_baggage_outbox import context as baggage_context, Driver as BaggageDriver
    consumer = baggage_context(monkeypatch, BaggageDriver(), [])
    bag = consumer.BagInZone(baggage_id="b1", tag="synthetic", flight_id="f1",
                             passenger_id="p1", is_dg=False, dg_class=None, terminal="B", entered_at=NOW.isoformat())
    for status in ("on_carousel", "collected"):
        plan = consumer._TickPlan()
        consumer._plan_status_change(plan, bag, "arrived", status, "arrival-belt-3", NOW, suppress=True)
        assert plan.status_changes[0]["passenger_id"] == "p1"
        assert plan.facts[0]["document"]["payload"]["passenger_id"] == "p1"

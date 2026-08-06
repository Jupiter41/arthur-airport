"""Redelivery idempotency test for the real cost-service Kafka consumer.

Unlike ``test_idempotency.py`` (which exercises the shared IdempotencyTracker in
isolation and re-implements the envelope validator), this test drives the actual
consumer dispatch — ``kafka.consumer.process_envelope`` — with only the I/O
boundary (Neo4j writes, Kafka emit) stubbed. It asserts that redelivering an
event with the same ``event_id`` does not mutate the cost/revenue running totals
a second time.

Kafka delivers at-least-once, so this guards against the double-counting bug
flagged in ROADMAP_REAL_LDT.md (§1.3 / P0).
"""

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from tests.conftest import import_service_module

FIXTURES_PATH = (
    Path(__file__).parent.parent.parent
    / "services" / "cost-service" / "fixtures" / "cost_rates.json"
)
with open(FIXTURES_PATH) as f:
    RATES = json.load(f)

FAKE_FLIGHT = {
    "aircraft_type": "A320",
    "pax_count": 180,
    "direction": "departure",
    "flight_number": "AF123",
    "distance_km": 2000.0,
}


def _departed_event(event_id: str) -> dict:
    """A FlightStatusChanged→departed envelope (triggers passenger + slot fees)."""
    return {
        "event_id": event_id,
        "event_type": "FlightStatusChanged",
        "sim_time": "2024-06-15T14:32:00Z",
        "payload": {
            "flight_id": "flight-1",
            "new_status": "departed",
            "day_of_sim": 1,
        },
    }


@pytest.fixture
def cost_ctx(monkeypatch):
    """Establish the cost-service module context and stub the I/O boundary.

    ``import_service_module`` mutates global ``sys.path``/``sys.modules``, and
    other service test files do the same at collection time — so the context is
    (re)built *inside the fixture*, at run time, right before the consumer's
    deferred ``from services.cost_engine import ...`` executes. Both the
    consumer and the engine are imported in the same context so they share one
    module graph and our patches land on the object the consumer actually uses.
    """
    consumer = import_service_module("cost", "kafka.consumer")
    engine = importlib.import_module("services.cost_engine")

    writes: list[dict] = []

    async def _fake_write_cost_record(record):
        writes.append(record)

    async def _noop_async(*args, **kwargs):
        return None

    async def _fake_get_flight_info(_flight_id):
        return dict(FAKE_FLIGHT)

    async def _fake_get_holding_flights():
        return []

    def _noop_emit(*args, **kwargs):
        return None

    # cost_engine imported these names into its own namespace, so patch there.
    monkeypatch.setattr(engine, "write_cost_record", _fake_write_cost_record)
    monkeypatch.setattr(engine, "get_flight_info", _fake_get_flight_info)
    monkeypatch.setattr(engine, "get_holding_flights", _fake_get_holding_flights)
    monkeypatch.setattr(engine, "link_cost_to_flight", _noop_async)
    monkeypatch.setattr(engine, "link_cost_to_incident", _noop_async)
    monkeypatch.setattr(engine, "link_cost_to_terminal", _noop_async)
    monkeypatch.setattr(engine, "link_cost_to_airport_day", _noop_async)
    monkeypatch.setattr(engine, "emit_cost_recorded", _noop_emit)

    # Real rates so the handler actually computes fees; no carbon factors.
    consumer.set_rates(RATES)
    consumer.set_carbon_factors({})

    # Reset running totals and the idempotency set.
    rt = engine._running_totals
    rt["total_cost_eur"] = 0.0
    rt["total_revenue_eur"] = 0.0
    rt["net_eur"] = 0.0
    rt["by_category"].clear()
    rt["eu261_exposure"] = 0.0
    rt["last_updated"] = None
    rt["sim_day"] = 1
    consumer.reset_idempotency()

    return consumer, engine, writes


def test_redelivery_does_not_double_count(cost_ctx):
    """Same event_id delivered twice mutates totals exactly once."""
    consumer, engine, writes = cost_ctx
    env = _departed_event("evt-dup-1")

    # First delivery — processed, totals move, records written.
    processed_first = asyncio.run(consumer.process_envelope(env))
    assert processed_first is True

    totals_after_first = engine.get_running_totals()
    writes_after_first = len(writes)
    assert totals_after_first["total_cost_eur"] > 0.0
    assert totals_after_first["total_revenue_eur"] > 0.0
    assert writes_after_first > 0

    # Redelivery of the *same* event_id — skipped before any mutation.
    processed_second = asyncio.run(consumer.process_envelope(env))
    assert processed_second is False

    totals_after_second = engine.get_running_totals()
    assert totals_after_second["total_cost_eur"] == totals_after_first["total_cost_eur"]
    assert totals_after_second["total_revenue_eur"] == totals_after_first["total_revenue_eur"]
    assert totals_after_second["net_eur"] == totals_after_first["net_eur"]
    # No further Neo4j writes on the duplicate.
    assert len(writes) == writes_after_first


def test_distinct_event_ids_both_processed(cost_ctx):
    """Two different event_ids each mutate totals (control for the dedup test)."""
    consumer, engine, writes = cost_ctx

    asyncio.run(consumer.process_envelope(_departed_event("evt-A")))
    cost_after_one = engine.get_running_totals()["total_cost_eur"]
    writes_after_one = len(writes)

    asyncio.run(consumer.process_envelope(_departed_event("evt-B")))
    cost_after_two = engine.get_running_totals()["total_cost_eur"]

    assert cost_after_two == pytest.approx(cost_after_one * 2)
    assert len(writes) == writes_after_one * 2


def test_empty_event_id_is_not_deduplicated(cost_ctx):
    """Events without an event_id are always processed (never treated as dup)."""
    consumer, engine, _writes = cost_ctx
    env = _departed_event("")  # empty id

    assert asyncio.run(consumer.process_envelope(env)) is True
    cost_after_one = engine.get_running_totals()["total_cost_eur"]

    # A second empty-id delivery is processed again — empty ids can't dedup,
    # so the tracker must not silently collapse them into one.
    assert asyncio.run(consumer.process_envelope(env)) is True
    cost_after_two = engine.get_running_totals()["total_cost_eur"]
    assert cost_after_two == pytest.approx(cost_after_one * 2)

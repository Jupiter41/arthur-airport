"""Real handlers and transaction orchestration; live tests also use Neo4j/Kafka."""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tests.conftest import import_service_module

FIXTURES = Path(__file__).resolve().parents[2] / "services/cost-service/fixtures"


def departed(event_id="synthetic-departure"):
    return {"event_id": event_id, "event_type": "FlightStatusChanged",
            "sim_time": "2026-01-01T12:30:00Z",
            "payload": {"flight_id": "synthetic-flight", "new_status": "departed", "day_of_sim": 1}}


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def single(self):
        return self.rows[0] if self.rows else None

    async def consume(self):
        pass

    async def data(self):
        return self.rows

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row
        return iterate()


class Driver:
    def __init__(self):
        self.db = {"document": None, "revision": 0, "inbox": set(),
                   "cost": [], "carbon": [], "outbox": {}}
        self.fail_once = None
        self.lose_commit_ack = False

    def session(self):
        driver = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def execute_write(self, callback):
                candidate = deepcopy(driver.db)
                result = await callback(Tx(driver, candidate))
                driver.db = candidate
                if driver.lose_commit_ack:
                    driver.lose_commit_ack = False
                    return await self.execute_write(callback)
                return result

            async def run(self, query, **params):
                return await Tx(driver, driver.db).run(query, **params)

        return Session()


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    async def run(self, query, **params):
        if self.driver.fail_once and self.driver.fail_once in query:
            self.driver.fail_once = None
            raise RuntimeError("Injected storage failure")
        db = self.db
        if "MERGE (s:CostRuntime" in query:
            db["revision"] += 1
            return Result([{"document": db["document"], "revision": db["revision"]}])
        if "MATCH (i:CostInbox" in query:
            return Result([{"id": params["id"]}] if params["id"] in db["inbox"] else [])
        if "CREATE (i:CostInbox" in query:
            db["document"] = params["document"]
            db["inbox"].add(params["id"])
        elif "SET s.document" in query:
            db["document"] = params["document"]
        elif "UNWIND $rows" in query:
            db["cost" if "CostRecord" in query else "carbon"].extend(params["rows"])
        elif "UNWIND $events" in query:
            db["outbox"].update({row["id"]: row for row in params["events"]})
        elif "MATCH (e:CostOutbox) RETURN" in query:
            return Result(db["outbox"].values())
        elif "DELETE e" in query:
            db["outbox"].pop(params["id"], None)
        elif "MATCH (c:CostRecord) RETURN" in query:
            return Result([row["record"] for row in db["cost"]])
        elif "MATCH (c:CarbonRecord) RETURN" in query:
            return Result([row["record"] for row in db["carbon"]])
        else:
            raise AssertionError(query)
        return Result()


@pytest.fixture
def cost_ctx(monkeypatch):
    consumer = import_service_module("cost", "kafka.consumer")
    engine = importlib.import_module("services.cost_engine")
    carbon = importlib.import_module("services.carbon_tracker")
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    flight = {"id": "synthetic-flight", "aircraft_type": "A320", "pax_count": 100,
              "direction": "departure", "flight_number": "ZZ001", "distance_km": 1200}
    monkeypatch.setattr(engine, "get_flight_info", AsyncMock(return_value=flight))
    monkeypatch.setattr(db, "get_flight_info", AsyncMock(return_value=flight))
    monkeypatch.setattr(engine, "get_holding_flights", AsyncMock(return_value=[]))
    consumer.set_rates(json.loads((FIXTURES / "cost_rates.json").read_text()))
    consumer.set_carbon_factors(json.loads((FIXTURES / "carbon_factors.json").read_text()))
    engine.init_running_totals({})
    engine.reset_daily_history()
    engine._gate_occupancy_starts.clear()
    carbon.init_carbon_totals({})
    return consumer, engine, carbon, driver


def test_redelivery_and_cache_loss_use_durable_inbox(cost_ctx):
    consumer, engine, carbon, driver = cost_ctx
    assert asyncio.run(consumer.process_envelope(departed())) is True
    saved_cost, saved_carbon = engine.get_running_totals(), carbon.get_carbon_totals()
    assert saved_cost["total_cost_eur"] > 0 and saved_carbon["total_kg"] > 0
    assert len(driver.db["cost"]) == 3 and len(driver.db["carbon"]) == 3
    engine.init_running_totals({})
    carbon.init_carbon_totals({})
    assert asyncio.run(consumer.process_envelope(departed())) is False
    assert engine.get_running_totals() == saved_cost
    assert carbon.get_carbon_totals() == saved_carbon
    assert len(driver.db["cost"]) == len(driver.db["carbon"]) == 3


@pytest.mark.parametrize("failure", ["CREATE (i:CostInbox", "UNWIND $events", "CREATE (c:CarbonRecord)"])
def test_partial_writes_roll_back_and_same_id_can_retry(cost_ctx, failure):
    consumer, engine, carbon, driver = cost_ctx
    before = deepcopy(driver.db)
    driver.fail_once = failure
    with pytest.raises(RuntimeError, match="Injected"):
        asyncio.run(consumer.process_envelope(departed()))
    assert driver.db == before
    assert engine.get_running_totals()["total_cost_eur"] == 0
    assert carbon.get_carbon_totals()["total_kg"] == 0
    assert asyncio.run(consumer.process_envelope(departed())) is True
    assert len(driver.db["cost"]) == len(driver.db["carbon"]) == 3
    assert len(driver.db["outbox"]) == 7


def test_lost_commit_ack_recovers_cache_without_second_charge(cost_ctx):
    consumer, engine, _, driver = cost_ctx
    driver.lose_commit_ack = True
    assert asyncio.run(consumer.process_envelope(departed())) is False
    assert engine.get_running_totals()["total_cost_eur"] > 0
    assert len(driver.db["cost"]) == 3


def test_gate_window_and_staffing_hour_survive_checkpoint_reload(cost_ctx):
    consumer, engine, _, driver = cost_ctx
    boarding = departed("boarding")
    boarding["sim_time"] = "2026-01-01T11:30:00Z"
    boarding["payload"]["new_status"] = "boarding"
    asyncio.run(consumer.process_envelope(boarding))
    engine._gate_occupancy_starts.clear()
    asyncio.run(consumer.ledger.initialize())
    assert "synthetic-flight" in engine._gate_occupancy_starts
    asyncio.run(consumer.process_envelope(departed()))
    assert sum(row["record"]["category"] == "gate_fee" for row in driver.db["cost"]) == 2
    tick = {"event_id": "clock-one", "event_type": "SimClockTick", "sim_time": "2026-01-01T12:40:00Z",
            "payload": {"day_of_sim": 1, "tick_number": 1}}
    asyncio.run(consumer.process_envelope(tick))
    staffing_count = sum(row["record"]["category"] == "staffing" for row in driver.db["cost"])
    assert staffing_count > 0
    asyncio.run(consumer.ledger.initialize())
    tick["event_id"] = "clock-two"
    asyncio.run(consumer.process_envelope(tick))
    assert sum(row["record"]["category"] == "staffing" for row in driver.db["cost"]) == staffing_count


def test_invalid_identity_rejected_and_distinct_events_remain_distinct(cost_ctx):
    consumer, engine, _, driver = cost_ctx
    with pytest.raises(ValidationError):
        asyncio.run(consumer.process_envelope(departed("")))
    assert not driver.db["inbox"]
    asyncio.run(consumer.process_envelope(departed("one")))
    first = engine.get_running_totals()["total_cost_eur"]
    asyncio.run(consumer.process_envelope(departed("two")))
    assert engine.get_running_totals()["total_cost_eur"] == pytest.approx(first * 2)


def test_broker_failure_retains_outbox_and_retries_identical_event_ids(cost_ctx, monkeypatch):
    consumer, _, _, driver = cost_ctx
    outbox = importlib.import_module("services.outbox")
    asyncio.run(consumer.process_envelope(departed()))
    seen = []

    def fail(event):
        seen.append(event["event_id"])
        raise RuntimeError("Broker unavailable")

    monkeypatch.setattr(outbox, "publish_confirmed", fail)
    with pytest.raises(RuntimeError):
        asyncio.run(outbox.publish_pending())
    assert len(driver.db["outbox"]) == 7
    monkeypatch.setattr(outbox, "publish_confirmed", lambda event: seen.append(event["event_id"]))
    assert asyncio.run(outbox.publish_pending()) == 7
    assert seen[0] == seen[1]
    assert not driver.db["outbox"]


def test_initial_checkpoint_preserves_legacy_ledger_and_eu261_exposure(cost_ctx):
    consumer, engine, carbon, driver = cost_ctx
    driver.db["cost"] = [{"record": {"sim_day": 3, "category": "eu261_compensation",
                                     "is_revenue": False, "amount_eur": 500, "sim_time": "2026-01-03T12:00:00Z"}}]
    driver.db["carbon"] = [{"record": {"sim_day": 3, "source": "terminal", "co2_kg": 8,
                                       "sim_time": "2026-01-03T12:00:00Z"}}]
    asyncio.run(consumer.ledger.initialize())
    assert engine.get_running_totals()["total_cost_eur"] == 500
    assert engine.get_running_totals()["eu261_exposure"] == 500
    assert carbon.get_carbon_totals()["total_kg"] == 8
    asyncio.run(consumer.ledger.initialize())
    assert engine.get_running_totals()["total_cost_eur"] == 500


def test_late_fact_is_charged_to_its_day_without_rewinding_current_summary(cost_ctx):
    consumer, engine, _, driver = cost_ctx
    tick = {"event_id": "day-three", "event_type": "SimClockTick", "sim_time": "2026-01-03T12:00:00Z",
            "payload": {"day_of_sim": 3, "tick_number": 1}}
    asyncio.run(consumer.process_envelope(tick))
    current = engine.get_running_totals()
    delayed = departed()
    delayed["payload"].pop("day_of_sim")
    delayed["sim_time"] = "2026-01-02T12:00:00Z"
    asyncio.run(consumer.process_envelope(delayed))
    assert all(row["record"]["sim_day"] == 2 for row in driver.db["cost"] if row["flight_id"])
    assert engine.get_running_totals() == current


@pytest.mark.parametrize("abort", [False, True])
def test_consumer_retries_before_batch_commit_and_never_commits_unfinished_batch(cost_ctx, monkeypatch, abort):
    consumer, _, _, driver = cost_ctx
    event = departed("")  # Broker position supplies stable identity.
    committed, attempts = [], []

    class Message:
        def error(self):
            return None

        def value(self):
            return json.dumps(event).encode()

        def topic(self):
            return "flights.events"

        def partition(self):
            return 1

        def offset(self):
            return 42

    class Broker:
        fetched = False

        def subscribe(self, topics):
            pass

        def consume(self, *args, **kwargs):
            if self.fetched:
                consumer.stop_consumer()
                return []
            self.fetched = True
            return [Message(), Message()]

        def commit(self, asynchronous):
            assert len(driver.db["cost"]) == 3
            assert driver.db["inbox"] == {"kafka:flights.events:1:42"}
            committed.append(True)

        def close(self):
            pass

    real_process = consumer.process_envelope

    async def process(envelope):
        attempts.append(envelope["event_id"])
        if abort:
            consumer.stop_consumer()
            raise RuntimeError("Shutdown during failed transaction")
        return await real_process(envelope)

    driver.fail_once = "UNWIND $events"
    monkeypatch.setattr(consumer, "make_consumer", Broker)
    monkeypatch.setattr(consumer, "process_envelope", process)
    asyncio.run(consumer.run_consumer())
    assert committed == ([] if abort else [True])
    assert len(attempts) == (1 if abort else 3)

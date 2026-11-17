"""Transfer bags of connecting passengers move from the inbound hold onto their onward flight."""

import asyncio
import importlib
import json
import sys
from datetime import date, datetime

from tests.conftest import import_service_module
from tests.unit.test_baggage_outbox import Driver, context

NOW = datetime(2026, 1, 1, 10)


def _facts(driver):
    return [json.loads(row["document"]) for row in driver.db["outbox"].values()]


def _arrival_at_gate(consumer, event_id="evt-arr"):
    return consumer._on_flight_status_changed(
        {"flight_id": "A1", "new_status": "at_gate", "previous_status": "taxiing", "gate_id": "A03"},
        NOW, event_id,
    )


def test_transfer_bags_reenter_the_bhs_on_their_open_onward_flight(monkeypatch):
    bags = [
        {"id": "t-open", "tag": "1", "status": "in_hold", "passenger_id": "p1", "transfer_flight_id": "D-open"},
        {"id": "t-gone", "tag": "2", "status": "in_hold", "passenger_id": "p2", "transfer_flight_id": "D-gone"},
        {"id": "t-unknown", "tag": "3", "status": "in_hold", "passenger_id": "p3", "transfer_flight_id": "D-x"},
        {"id": "local", "tag": "4", "status": "in_hold", "passenger_id": None, "transfer_flight_id": None},
    ]
    driver = Driver()
    consumer = context(monkeypatch, driver, bags)
    relinked: list = []

    async def relink(tx, rows):
        relinked.extend(rows)

    monkeypatch.setattr(sys.modules["db.neo4j"], "relink_transfer_baggage_tx", relink)
    fv = importlib.import_module("_common.flight_view")
    fv.VIEW.load([
        {"id": "D-open", "direction": "departure", "status": "boarding", "gate_id": "C12"},
        {"id": "D-gone", "direction": "departure", "status": "departed", "gate_id": "B02"},
    ], [], None)
    try:
        asyncio.run(_arrival_at_gate(consumer))
        asyncio.run(_arrival_at_gate(consumer))          # redelivery: deduped by the inbox
    finally:
        fv.VIEW.load([], [], None)

    assert relinked == [{"id": "t-open", "inbound_flight_id": "A1", "onward_flight_id": "D-open"}]
    bags_db = driver.db["baggage"]
    assert bags_db["t-open"]["status"] == "dropped_off" and bags_db["t-open"]["zone"] == "transfer-C"
    assert {bags_db[b]["status"] for b in ("t-gone", "t-unknown", "local")} == {"arrived"}
    transfer = [f["payload"] for f in _facts(driver) if f["payload"].get("new_status") == "dropped_off"]
    assert transfer == [{
        "baggage_id": "t-open", "tag": "1", "passenger_id": "p1", "flight_id": "D-open",
        "previous_status": "in_hold", "new_status": "dropped_off", "scan_zone": "transfer-C",
        "at": NOW.isoformat(), "inbound_flight_id": "A1",
    }]
    # Only the three arrival bags reach the in-memory belt.
    belts = [z for z in consumer._state.conveyor._zones.values() if z.zone_id.startswith("arrival-belt")]
    assert sorted(b.baggage_id for z in belts for b in z.queue) == ["local", "t-gone", "t-unknown"]


def test_transfer_facts_are_kept_in_bulk_mode(monkeypatch):
    bags = [{"id": "t1", "tag": "1", "status": "in_hold", "passenger_id": "p1", "transfer_flight_id": "D1"}]
    driver = Driver()
    consumer = context(monkeypatch, driver, bags)
    monkeypatch.setattr(consumer, "is_bulk_mode", lambda: True)

    async def relink(tx, rows):
        return None

    monkeypatch.setattr(sys.modules["db.neo4j"], "relink_transfer_baggage_tx", relink)
    fv = importlib.import_module("_common.flight_view")
    fv.VIEW.load([{"id": "D1", "direction": "departure", "status": "scheduled", "gate_id": "B04"}], [], None)
    try:
        asyncio.run(_arrival_at_gate(consumer))
    finally:
        fv.VIEW.load([], [], None)
    assert [f["payload"]["new_status"] for f in _facts(driver)] == ["dropped_off"]


def test_seeder_gives_connecting_passengers_transfer_bags():
    schedule = import_service_module("sim", "services.schedule")
    passengers = importlib.import_module("services.passengers")
    baggage = importlib.import_module("services.baggage")
    importlib.import_module("services.fixtures").load_fixtures()

    async def noop(*args, **kwargs):
        return None

    schedule._persist_flights = noop
    passengers._persist_passengers = noop
    passengers._update_flight_pax_counts = noop
    baggage._persist_arrival_baggage = noop
    baggage._persist_transfer_baggage = noop

    async def run():
        flights = await schedule.generate_schedule(date(2024, 6, 15), target_departures=120, seed=7)
        deps = [f for f in flights if f["direction"] == "departure" and f.get("flight_type") != "cargo"]
        arrs = [f for f in flights if f["direction"] == "arrival" and f.get("flight_type") != "cargo"]
        _, pax = await passengers.generate_passengers(
            arrs, seed=8, initial_status="airborne", onward_departures=deps)
        _, with_pax = await baggage.generate_arrival_baggage(arrs, seed=9, arrival_passengers=pax)
        _, without = await baggage.generate_arrival_baggage(arrs, seed=9, arrival_passengers=pax)
        return pax, with_pax, without

    pax, with_pax, without = asyncio.run(run())
    onward = {p["id"]: p["connection_flight_id"] for p in pax if p["connection"]}
    transfer = [b for b in with_pax if b.get("transfer_flight_id")]
    assert transfer and all(onward[b["passenger_id"]] == b["transfer_flight_id"] for b in transfer)
    assert all(b["status"] == "in_hold" and b["flight_id"] != b["transfer_flight_id"] for b in transfer)
    assert all(b.get("passenger_id") for b in with_pax)
    assert len({b["tag"] for b in with_pax}) == len(with_pax)
    # Total arrival volume stays of the same order: transfer bags replace anonymous ones.
    assert 0.5 < len(with_pax) / len(without) < 1.5

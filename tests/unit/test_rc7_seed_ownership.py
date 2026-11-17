"""Seed manifests preserve ownership, arrival identity and inbound causality."""
import asyncio
import importlib
from collections import Counter
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

from tests.conftest import import_service_module


def test_generated_arrivals_have_named_bags_connections_and_no_airport_show_up():
    schedule = import_service_module("sim", "services.schedule")
    passengers = importlib.import_module("services.passengers")
    baggage = importlib.import_module("services.baggage")
    importlib.import_module("services.fixtures").load_fixtures()

    async def run():
        flights = await schedule.generate_schedule(date(2024, 6, 15), target_departures=30, seed=7)
        deps = [f for f in flights if f["direction"] == "departure"]
        arrs = [f for f in flights if f["direction"] == "arrival"]
        _, pax = await passengers.generate_passengers(arrs, seed=8, onward_departures=deps)
        _, bags = await baggage.generate_arrival_baggage(arrs, seed=9, arrival_passengers=pax)
        return pax, bags

    pax, bags = asyncio.run(run())
    by_id = {p["id"]: p for p in pax}
    assert bags and all(p["status"] == "booked" and p["show_up_at"] is None for p in pax)
    assert any(not b["transfer_flight_id"] for b in bags)
    for bag in bags:
        passenger = by_id[bag["passenger_id"]]
        assert bag["flight_id"] == passenger["flight_id"]
        assert bag["transfer_flight_id"] == passenger["connection_flight_id"]
        assert bag["status"] == "in_hold"
    counts = Counter(b["passenger_id"] for b in bags)
    assert max(counts.values()) <= baggage._bag_config().max_bags_per_pax
    # Generators no longer expose cross-domain persistence helpers.
    assert not hasattr(schedule, "_persist_flights")
    assert not hasattr(passengers, "_persist_passengers")
    assert not hasattr(baggage, "_persist_baggage")


def test_seed_day_stores_complete_manifest_before_notification(monkeypatch):
    seeder = import_service_module("sim", "services.seeder")
    importlib.import_module("services.fixtures").load_fixtures()
    requests = importlib.import_module("_common.seed_requests")
    stored = []

    async def store(driver, day, at, manifests):
        stored.append(manifests)
        return True

    def notify(at, day, flights, **kwargs):
        assert stored
        assert kwargs["seed_day_id"] == (seeder.SIM_START_TIME + timedelta(days=1)).date().isoformat()
        assert all(p["status"] == "booked" for p in stored[0]["passenger"])
        actual = Counter(p["flight_id"] for p in stored[0]["passenger"])
        actual.update(p["connection_flight_id"] for p in stored[0]["passenger"] if p["connection_flight_id"])
        assert all(f["pax_count"] == actual[f["id"]] for f in flights)

    monkeypatch.setattr(seeder, "_day_already_seeded", AsyncMock(return_value=False))
    monkeypatch.setattr(seeder, "_daily_flight_target", lambda: 40)
    monkeypatch.setattr(seeder, "_check_bhs_capacity", lambda *args: [])
    monkeypatch.setattr(requests, "store_day", store)
    monkeypatch.setattr(seeder, "emit_flight_schedule_seeded", notify)
    asyncio.run(seeder.seed_day(2))
    assert len(stored) == 1


def test_arrival_flight_becomes_airborne_at_origin_departure_boundary():
    machine = import_service_module("flight", "services.state_machine")
    eta = datetime(2024, 6, 15, 12)
    flight = {"direction": "arrival", "status": "scheduled", "estimated_time": eta.isoformat(),
              "flight_duration_minutes": 120}
    assert machine.evaluate_transition(flight, eta - timedelta(minutes=121)) is None
    assert machine.evaluate_transition(flight, eta - timedelta(minutes=120)) == "airborne"
    assert machine.evaluate_transition(flight, eta - timedelta(minutes=20)) == "approach"


def test_arrival_reconciliation_requires_a_consumed_flight_lifecycle():
    rules = import_service_module("passenger", "services.reconciliation")
    now = datetime(2024, 6, 15, 10)
    pax = {"status": "booked", "direction": "arrival", "scheduled_time": "2024-06-15T12:00:00"}
    assert rules.reconciliation_transition({**pax, "flight_status": "scheduled"}, now) is None
    assert rules.reconciliation_transition({**pax, "flight_status": "airborne"}, now) == ("airborne", "in-flight")

"""RC6 — bag volume sized against BHS capacity; no teleport-to-hold at departure.

DATA_FLOW_REVIEW.md RC6: generated demand peaked at ~2.7× the baggage-handling
capacity and the departure handler hid the backlog by moving every unscreened
bag to ``in_hold``. These tests pin both halves of the fix:

* the shipped ``config/airport.yaml`` passes the seed-time sizing check
  (peak hourly bags ≤ 85% of the slowest stage, per terminal and airport-wide)
  over several generated days, and the check does catch the old sizing;
* at departure only ``loaded`` bags reach the hold; the rest are short-shipped
  with one ``BaggageMissedFlight`` fact.
"""

import asyncio
import importlib
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.conftest import import_service_module
from tests.unit.test_baggage_outbox import Driver, context, departed

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

from _common.airport_config import BaggageSystemConfig, load_airport_runtime_config  # noqa: E402
from _common.bhs_capacity import check_capacity, demand_by_terminal_hour  # noqa: E402


# ── sizing ─────────────────────────────────────────────────────────────────


def _generate_day(day: int):
    """Run the real schedule/passenger/baggage generators without Neo4j."""
    schedule = import_service_module("sim", "services.schedule")
    passengers = importlib.import_module("services.passengers")
    baggage = importlib.import_module("services.baggage")
    importlib.import_module("services.fixtures").load_fixtures()

    async def noop(*args, **kwargs):
        return None

    schedule._persist_flights = noop
    passengers._persist_passengers = noop
    passengers._update_flight_pax_counts = noop
    baggage._persist_baggage = noop

    async def run():
        target = load_airport_runtime_config().simulation.daily_flight_target // 2
        sim_date = date(2024, 6, 14) + timedelta(days=day)
        flights = await schedule.generate_schedule(sim_date, target_departures=target, seed=42 + day)
        deps = [f for f in flights if f["direction"] == "departure" and f.get("flight_type") != "cargo"]
        n_pax, pax = await passengers.generate_passengers(deps, seed=42 + day + 1000)
        types = {f["id"]: f.get("flight_type", "") for f in flights}
        _, bags = await baggage.generate_baggage(pax, seed=42 + day + 2000, flight_type_map=types)
        return deps, pax, bags

    return asyncio.run(run())


@pytest.fixture(scope="module")
def generated_days():
    return [_generate_day(day) for day in range(1, 5)]


def test_shipped_config_keeps_peak_bags_under_bhs_headroom(generated_days):
    cfg = load_airport_runtime_config().operations.baggage
    for deps, _, bags in generated_days:
        demand = demand_by_terminal_hour(bags, {f["id"]: f for f in deps})
        assert check_capacity(demand, cfg) == []


def test_bag_volume_has_no_one_bag_floor(generated_days):
    for _, pax, bags in generated_days:
        per_pax = Counter(b["passenger_id"] for b in bags)
        carry_on_only = sum(1 for p in pax if per_pax[p["id"]] == 0)
        assert 0.6 <= len(bags) / len(pax) <= 1.0      # was ~1.56 with the floor
        assert carry_on_only / len(pax) > 0.3           # zero checked bags is common


def test_check_flags_the_pre_rc6_sizing(generated_days):
    """The old 600/300/1,800 per-hour BHS fails against today's demand too."""
    old = BaggageSystemConfig(
        induction_per_terminal_hr={"A": 600, "B": 600, "C": 600},
        screening_per_terminal_hr={"A": 600, "B": 600, "C": 600},
        sorting_matrix_hr=1800,
    )
    deps, _, bags = generated_days[0]
    violations = check_capacity(demand_by_terminal_hour(bags, {f["id"]: f for f in deps}), old)
    scopes = {v["scope"] for v in violations}
    assert {"B", "airport"} <= scopes
    assert all(v["peak_bags"] > v["limit"] for v in violations)


def test_check_reports_terminal_and_airport_scopes_independently():
    cfg = BaggageSystemConfig(
        induction_per_terminal_hr={"A": 100, "B": 1000}, screening_per_terminal_hr={"A": 100, "B": 1000},
        sorting_matrix_hr=10_000, capacity_headroom=0.5,
    )
    demand = Counter({("A", 8): 60, ("A", 9): 10, ("B", 8): 400})
    [violation] = check_capacity(demand, cfg)
    assert violation == {"scope": "A", "hour": 8, "peak_bags": 60, "capacity_hr": 100,
                         "limit": 50, "utilisation": 0.6}


@pytest.fixture
def isolated_registry():
    """Drop collectors registered by this test so later sim imports stay clean."""
    import prometheus_client
    registry = prometheus_client.REGISTRY
    before = set(registry._collector_to_names)
    yield
    for collector in set(registry._collector_to_names) - before:
        registry.unregister(collector)


def test_seeder_counts_and_logs_sizing_violations(monkeypatch, caplog, isolated_registry):
    seeder = import_service_module("sim", "services.seeder")
    metrics = sys.modules["metrics"]
    before = metrics.sim_bhs_capacity_violations_total.labels(scope="B")._value.get()
    flights = [{"id": "f1", "gate_id": "B04", "scheduled_time": "2024-06-15T08:10:00"}]
    bags = [{"flight_id": "f1"}] * 3000  # > 0.85 × 3000 (B), < 0.85 × 5400 (airport)
    with caplog.at_level("WARNING"):
        violations = seeder._check_bhs_capacity(flights, bags)
    assert {v["scope"] for v in violations} == {"B"}
    assert metrics.sim_bhs_capacity_violations_total.labels(scope="B")._value.get() == before + 1
    assert "BHS sizing: B peak 3000 bags at 08h" in caplog.text


# ── departure outcome ──────────────────────────────────────────────────────


def _facts(driver):
    return [json.loads(row["document"]) for row in driver.db["outbox"].values()]


def test_every_unloaded_stage_is_short_shipped_never_held(monkeypatch):
    bags = [
        {"id": f"b-{status}", "tag": f"t-{status}", "status": status, "passenger_id": None}
        for status in ("dropped_off", "inducted", "screening", "sorting", "loaded")
    ]
    driver = Driver()
    consumer = context(monkeypatch, driver, bags)
    asyncio.run(departed(consumer, "evt-dep"))

    statuses = {bag_id: row["status"] for bag_id, row in driver.db["baggage"].items()}
    assert statuses == {
        "b-dropped_off": "short_shipped", "b-inducted": "short_shipped",
        "b-screening": "short_shipped", "b-sorting": "short_shipped", "b-loaded": "in_hold",
    }
    [missed] = [f for f in _facts(driver) if f["event_type"] == "BaggageMissedFlight"]
    assert missed["payload"]["flight_id"] == "f1"
    assert missed["payload"]["count"] == 4
    assert missed["payload"]["by_previous_status"] == {
        "dropped_off": 1, "inducted": 1, "screening": 1, "sorting": 1,
    }


def test_departure_with_everything_loaded_emits_no_missed_flight(monkeypatch):
    bags = [{"id": "b1", "tag": "t1", "status": "loaded", "passenger_id": None}]
    driver = Driver()
    consumer = context(monkeypatch, driver, bags)
    asyncio.run(departed(consumer, "evt-dep"))
    assert driver.db["baggage"]["b1"]["status"] == "in_hold"
    assert [f["event_type"] for f in _facts(driver)] == ["BaggageStatusChanged"]


def test_missed_flight_fact_survives_bulk_mode(monkeypatch):
    bags = [{"id": "b1", "tag": "t1", "status": "screening", "passenger_id": None}]
    driver = Driver()
    consumer = context(monkeypatch, driver, bags)
    monkeypatch.setattr(consumer, "is_bulk_mode", lambda: True)
    asyncio.run(departed(consumer, "evt-dep"))
    assert driver.db["baggage"]["b1"]["status"] == "short_shipped"
    assert [f["event_type"] for f in _facts(driver)] == ["BaggageMissedFlight"]


def test_departure_queries_only_loaded_and_on_ground_statuses(monkeypatch):
    driver = Driver()
    consumer = context(monkeypatch, driver, [])
    asyncio.run(departed(consumer, "evt-dep"))
    query = sys.modules["db.neo4j"].get_flight_baggage
    statuses = query.await_args.kwargs["statuses"]
    assert set(statuses) == {"loaded", "dropped_off", "inducted", "screening", "sorting"}
    # Flagged / held-for-review bags are left to the review flow, not the hold.
    assert "flagged" not in statuses and "held_for_review" not in statuses
